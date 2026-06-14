import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Rectangle
from matplotlib.backends.backend_pdf import PdfPages
from datetime import datetime, timedelta
import warnings
import io
import os
import sys

# ================= 全局设置 =================
warnings.filterwarnings('ignore')

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'WenQuanYi Micro Hei', 'DejaVu Sans', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['pdf.fonttype'] = 42

st.set_page_config(page_title="基金绩效深度分析系统", layout="wide", initial_sidebar_state="expanded")

# ================= 样式配置 =================
st.markdown("""
<style>
    .main-title { font-size: 32px; font-weight: bold; color: #2E75B6; text-align: center; margin-bottom: 20px; }
    .metric-card { background-color: #f0f2f6; border-radius: 10px; padding: 15px; margin: 5px; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { height: 40px; font-weight: 600; }
    div[data-testid="stDownloadButton"] > button { width: 100%; background-color: #2E75B6; color: white; font-weight: bold; }
    .calc-button { font-size: 20px !important; padding: 15px 30px !important; }
</style>
""", unsafe_allow_html=True)

# ================= Session State 初始化 =================
if 'raw_df' not in st.session_state:
    st.session_state.raw_df = None
if 'results_sorted' not in st.session_state:
    st.session_state.results_sorted = None
if 'hs300_df' not in st.session_state:
    st.session_state.hs300_df = None
if 'global_start_date' not in st.session_state:
    st.session_state.global_start_date = None
if 'global_end_date' not in st.session_state:
    st.session_state.global_end_date = None
if 'code_to_name' not in st.session_state:
    st.session_state.code_to_name = {}
if 'file_stem' not in st.session_state:
    st.session_state.file_stem = ""
if 'calc_done' not in st.session_state:
    st.session_state.calc_done = False
if 'pdf_bytes' not in st.session_state:
    st.session_state.pdf_bytes = None
if 'pdf_generated' not in st.session_state:
    st.session_state.pdf_generated = False

# ================= 侧边栏配置 =================
with st.sidebar:
    st.header("⚙️ 分析配置")

    uploaded_file = st.file_uploader("📁 上传 CSV 文件", type=['csv'], 
                                     help="文件需包含：基金代码(JJDM/FundCode)、日期(DATE1/Date)、净值(NAV1/NAV)列")

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        trading_days = st.number_input("年交易天数", value=244, min_value=1, step=1, key="cfg_trading_days")
        risk_free_rate = st.number_input("无风险利率", value=0.0184, format="%.4f", step=0.0001, key="cfg_risk_free")
    with col2:
        min_years = st.number_input("最小年限(年)", value=1.0, min_value=0.1, step=0.1, key="cfg_min_years")
        benchmark_name = st.text_input("业绩基准", value="沪深300指数", key="cfg_benchmark_name")

    benchmark_code = st.text_input("基准代码", value="sh000300", 
                                   help="如 sh000300, sz399006 等", key="cfg_benchmark_code")

    st.divider()

    # 重置按钮
    if st.button("🔄 重置分析", use_container_width=True):
        for key in ['raw_df', 'results_sorted', 'hs300_df', 'global_start_date', 
                    'global_end_date', 'code_to_name', 'file_stem', 'calc_done',
                    'pdf_bytes', 'pdf_generated']:
            st.session_state[key] = None if key not in ['calc_done', 'pdf_generated'] else False
        st.session_state.file_stem = ""
        st.rerun()

    st.caption("📌 支持的列名映射：\n基金代码: JJDM/FundCode/基金代码\n日期: DATE1/Date/NAV_DATE/日期\n净值: NAV1/NAV/UNIT_NAV/单位净值")

# ================= 常量配置（从侧边栏读取）====================
RISK_FREE_RATE = risk_free_rate
TRADING_DAYS_PER_YEAR = trading_days
MIN_YEARS_REQUIRED = min_years
BENCHMARK_CODE = benchmark_code
BENCHMARK_NAME = benchmark_name
DISCLAIMER_TEXT = "注：本报告数据基于历史业绩计算，不代表未来表现。投资有风险，入市需谨慎。"

# ================= 数据读取函数 =================
@st.cache_data(show_spinner=False)
def load_and_clean_data(file_bytes):
    try:
        df = pd.read_csv(io.BytesIO(file_bytes), encoding='gbk')
    except:
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), encoding='utf-8-sig')
        except:
            try:
                df = pd.read_csv(io.BytesIO(file_bytes), encoding='utf-8')
            except Exception as e:
                st.error(f"❌ 无法读取文件: {e}")
                return None
    col_map = {
        'JJDM': 'FundCode', 'FUND_CODE': 'FundCode', '基金代码': 'FundCode',
        'FUND_NAME': 'FundName', '基金名称': 'FundName',
        'DATE1': 'Date', 'NAV_DATE': 'Date', '日期': 'Date',
        'NAV1': 'NAV', 'UNIT_NAV': 'NAV', '单位净值': 'NAV'
    }
    df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)
    required = ['FundCode', 'Date', 'NAV']
    missing = [c for c in required if c not in df.columns]
    if missing:
        st.error(f"❌ 缺少必要列: {missing}。当前列名: {list(df.columns)}")
        return None
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df['NAV'] = pd.to_numeric(df['NAV'], errors='coerce')
    df = df.dropna(subset=['Date', 'NAV'])
    df = df.sort_values(by=['FundCode', 'Date']).reset_index(drop=True)
    if 'FundName' not in df.columns:
        df['FundName'] = df['FundCode']
    return df

# ================= 获取基准数据 =================
@st.cache_data(show_spinner=False)
def get_benchmark_data(bm_code):
    try:
        import akshare as ak
        hs300_raw = ak.stock_zh_index_daily(symbol=bm_code)
        if not hs300_raw.empty:
            hs300_raw['date'] = pd.to_datetime(hs300_raw['date'])
            hs300_df = hs300_raw.set_index('date')[['close']]
            hs300_df.columns = ['benchmark_nav']
            hs300_df = hs300_df[hs300_df['benchmark_nav'] > 0]
            return hs300_df
    except Exception as e:
        st.warning(f"⚠️ 基准数据获取失败: {e}")
    return None

# ================= 核心计算函数（完全参照PDF版本）====================
def calculate_metrics(group_df, benchmark_series=None):
    nav = group_df['NAV'].values
    dates = group_df['Date'].values
    n_days = len(nav)
    if n_days < 2:
        return None
    fund_code = group_df['FundCode'].iloc[0]
    fund_name = group_df['FundName'].iloc[0] if 'FundName' in group_df.columns else fund_code
    daily_returns = np.diff(nav) / nav[:-1]
    total_return = (nav[-1] - nav[0]) / nav[0]
    years = n_days / TRADING_DAYS_PER_YEAR
    ann_return = (nav[-1] / nav[0]) ** (1 / years) - 1 if years > 0 else 0.0
    volatility = np.std(daily_returns, ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)
    sharpe = (ann_return - RISK_FREE_RATE) / volatility if volatility != 0 else 0.0
    peak = nav[0]
    max_dd = 0.0
    for price in nav:
        if price > peak:
            peak = price
        dd = (peak - price) / peak
        if dd > max_dd:
            max_dd = dd
    calmar = ann_return / max_dd if max_dd != 0 else np.nan
    if max_dd == 0 and ann_return > 0:
        calmar = 99.99
    downside_returns = daily_returns[daily_returns < 0]
    sortino = np.nan
    if len(downside_returns) > 1:
        downside_std = np.std(downside_returns, ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)
        if downside_std != 0:
            sortino = (ann_return - RISK_FREE_RATE) / downside_std
    elif ann_return > RISK_FREE_RATE:
        sortino = 99.99
    win_mask = daily_returns > 0
    loss_mask = daily_returns < 0
    win_count = np.sum(win_mask)
    loss_count = np.sum(loss_mask)
    win_rate = win_count / len(daily_returns) if len(daily_returns) > 0 else 0.0
    avg_win = np.mean(daily_returns[win_mask]) if win_count > 0 else 0.0
    avg_loss = np.mean(daily_returns[loss_mask]) if loss_count > 0 else 0.0
    pl_ratio = avg_win / abs(avg_loss) if avg_loss != 0 else np.nan
    info_ratio = np.nan
    tracking_error = np.nan
    alpha_annual = np.nan
    if benchmark_series is not None:
        fund_series = pd.Series(nav, index=pd.to_datetime(dates))
        common_dates = fund_series.index.intersection(benchmark_series.index)
        if len(common_dates) > 20:
            f_ret = fund_series.loc[common_dates].pct_change().dropna()
            b_ret = benchmark_series.loc[common_dates].pct_change().dropna()
            common_idx = f_ret.index.intersection(b_ret.index)
            if len(common_idx) > 0:
                active_ret = f_ret.loc[common_idx] - b_ret.loc[common_idx]
                te = active_ret.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
                ann_active = active_ret.mean() * TRADING_DAYS_PER_YEAR
                if te != 0:
                    info_ratio = ann_active / te
                    tracking_error = te
                    alpha_annual = ann_active
    return pd.Series({
        "基金代码": fund_code, "基金名称": fund_name, "年限": round(years, 2),
        "累计收益率": total_return, "年化收益率": ann_return, "年化波动率": volatility,
        "夏普比率": sharpe, "索提诺比率": sortino, "卡玛比率": calmar,
        "胜率": win_rate, "盈亏比": pl_ratio, "最大回撤": max_dd,
        "信息比率": info_ratio, "年化超额收益": alpha_annual, "跟踪误差": tracking_error
    })

# ================= PDF生成函数（完全参照PDF版本）====================
def generate_pdf_report(df, results_sorted, hs300_df, global_start_date, global_end_date, file_stem):
    """生成与PDF版本完全一致的10页报告"""
    output_buffer = io.BytesIO()
    pdf = PdfPages(output_buffer)
    TOTAL_PAGES = 10
    code_to_name = df.groupby('FundCode')['FundName'].first().to_dict()

    def add_footer(fig, page_num):
        try:
            ax = fig.add_axes([0, 0, 1, 1])
            ax.axis('off')
            ax.text(0.98, 0.02, f"Page {page_num} / {TOTAL_PAGES}", ha='right', va='bottom',
                   fontsize=9, color='#555555', fontweight='bold', transform=ax.transAxes)
            if 1 < page_num < TOTAL_PAGES:
                ax.text(0.5, 0.02, DISCLAIMER_TEXT, ha='center', va='bottom',
                       fontsize=8, style='italic', color='#666666', transform=ax.transAxes)
        except:
            pass

    def safe_save(fig, page_num, name):
        try:
            add_footer(fig, page_num)
            pdf.savefig(fig, bbox_inches='tight')
            plt.close(fig)
            return True
        except Exception as e:
            plt.close(fig)
            return False

    date_range = f"{global_start_date.strftime('%Y-%m-%d')} 至 {global_end_date.strftime('%Y-%m-%d')}"

    # Page 1: 封面
    try:
        fig = plt.figure(figsize=(8.27, 11.69))
        ax = fig.add_axes([0, 0, 1, 1])
        ax.axis('off')
        rect_top = Rectangle((0, 0.75), 1, 0.25, transform=ax.transAxes, color='#EBF4FA', alpha=1.0)
        ax.add_patch(rect_top)
        bg_ax = fig.add_axes([0, 0.75, 1, 0.25])
        bg_ax.axis('off')
        if len(results_sorted) > 0:
            top_codes = results_sorted.head(3)['基金代码'].tolist()
            bg_df = df[df['FundCode'].isin(top_codes)]
            if not bg_df.empty:
                bg_df_grouped = bg_df.groupby('Date')['NAV'].mean()
                bg_df_norm = bg_df_grouped / bg_df_grouped.iloc[0]
                bg_ax.plot(bg_df_norm.index, bg_df_norm.values, color='#2E75B6', linewidth=2, alpha=0.15)
                bg_ax.fill_between(bg_df_norm.index, bg_df_norm.values, bg_df_norm.min(), color='#2E75B6', alpha=0.05)
                bg_ax.set_ylim(bottom=bg_df_norm.min()*0.95, top=bg_df_norm.max()*1.05)
                bg_ax.set_xlim(bg_df_norm.index.min(), bg_df_norm.index.max())
        title_y = 0.88
        ax.text(0.5, title_y, "基金深度绩效分析报告", ha='center', va='center',
                fontsize=32, fontweight='bold', color='#2E75B6', transform=ax.transAxes, zorder=10)
        ax.text(0.5, title_y - 0.04, f"({file_stem})", ha='center', va='center',
                fontsize=20, color='#555555', transform=ax.transAxes, zorder=10)
        ax.plot([0.3, 0.7], [title_y - 0.08, title_y - 0.08], color='#2E75B6', linewidth=3, transform=ax.transAxes, zorder=10)
        card_x = 0.15
        card_y_start = 0.65
        card_width = 0.7
        card_height = 0.22
        card_bg = Rectangle((card_x, card_y_start - card_height), card_width, card_height,
                            transform=ax.transAxes, color='#FFFFFF', alpha=0.95, ec='#E9ECEF', lw=1, zorder=5)
        ax.add_patch(card_bg)
        left_col_x = card_x + 0.05
        right_col_x = card_x + 0.38
        row_height = 0.06
        font_size_label = 13
        font_size_value = 13
        text_color = '#333333'
        label_color = '#666666'
        current_y = card_y_start - 0.04
        ax.text(left_col_x, current_y, "分析区间", ha='left', va='top', fontsize=font_size_label, color=label_color, transform=ax.transAxes, zorder=6)
        ax.text(left_col_x + 0.12, current_y, date_range, ha='left', va='top', fontsize=font_size_value, fontweight='bold', color=text_color, transform=ax.transAxes, zorder=6)
        current_y -= row_height
        ax.text(left_col_x, current_y, "有效基金", ha='left', va='top', fontsize=font_size_label, color=label_color, transform=ax.transAxes, zorder=6)
        ax.text(left_col_x + 0.12, current_y, f"{len(results_sorted)} 只", ha='left', va='top', fontsize=font_size_value, fontweight='bold', color=text_color, transform=ax.transAxes, zorder=6)
        ax.text(right_col_x, current_y, "业绩基准", ha='left', va='top', fontsize=font_size_label, color=label_color, transform=ax.transAxes, zorder=6)
        ax.text(right_col_x + 0.12, current_y, BENCHMARK_NAME, ha='left', va='top', fontsize=font_size_value, fontweight='bold', color=text_color, transform=ax.transAxes, zorder=6)
        current_y -= row_height
        ax.text(left_col_x, current_y, "年交易天数", ha='left', va='top', fontsize=font_size_label, color=label_color, transform=ax.transAxes, zorder=6)
        ax.text(left_col_x + 0.12, current_y, f"{TRADING_DAYS_PER_YEAR} 天", ha='left', va='top', fontsize=font_size_value, fontweight='bold', color=text_color, transform=ax.transAxes, zorder=6)
        ax.text(right_col_x, current_y, "无风险利率", ha='left', va='top', fontsize=font_size_label, color=label_color, transform=ax.transAxes, zorder=6)
        ax.text(right_col_x + 0.12, current_y, f"{RISK_FREE_RATE:.2%}", ha='left', va='top', fontsize=font_size_value, fontweight='bold', color=text_color, transform=ax.transAxes, zorder=6)
        bottom_area_y = 0.08
        report_date = datetime.now().strftime('%Y-%m-%d')
        ax.text(0.5, bottom_area_y, f"报告生成日：{report_date}", ha='center', va='bottom',
                fontsize=14, color='#555555', fontweight='bold', transform=ax.transAxes, zorder=6)
        ax.text(0.5, bottom_area_y - 0.04, DISCLAIMER_TEXT, ha='center', va='bottom',
                fontsize=9, style='italic', color='#666666', transform=ax.transAxes, zorder=6)
        safe_save(fig, 1, "封面")
    except Exception as e:
        pass

    # Page 2: 目录
    try:
        fig = plt.figure(figsize=(8.27, 11.69))
        ax = fig.add_axes([0, 0, 1, 1])
        ax.axis('off')
        ax.text(0.5, 0.92, "目 录", ha='center', fontsize=28, fontweight='bold', color='#2E75B6', transform=ax.transAxes)
        ax.plot([0.3, 0.7], [0.88, 0.88], color='#2E75B6', linewidth=2, transform=ax.transAxes)
        toc_list = [
            ("1. 累计净值走势 (Top 10)", 3),
            ("2. 多周期动态收益对比 (Top 10)", 4),
            ("3. 夏普比率气泡图", 5),
            ("4. 风险收益分布散点图", 6),
            ("5. 信息比率 vs 跟踪误差", 7),
            ("6. Top 10 基金深度绩效明细表", 8),
            ("7. Top 10 基金深度分析解读", 9),
            ("8. 附录：核心指标说明", 10)
        ]
        line_gap = 0.025
        start_y_toc = 0.85
        for i, (title, page) in enumerate(toc_list):
            y_pos = start_y_toc - i * line_gap
            ax.text(0.2, y_pos, title, ha='left', va='center', fontsize=16, color='#333333', transform=ax.transAxes)
            ax.text(0.8, y_pos, f"... Page {page}", ha='right', va='center', fontsize=16, color='#666666', transform=ax.transAxes)
            ax.plot([0.45, 0.75], [y_pos, y_pos], linestyle=':', color='#CCCCCC', transform=ax.transAxes)
        safe_save(fig, 2, "目录")
    except Exception as e:
        pass

    # Page 3: 净值走势
    try:
        fig = plt.figure(figsize=(10, 7))
        ax = fig.add_axes([0.12, 0.12, 0.86, 0.80])
        top_codes = results_sorted.head(10)["基金代码"].tolist()
        df_plot = df[df['FundCode'].isin(top_codes)]
        if hs300_df is not None:
            bp = hs300_df[(hs300_df.index >= global_start_date) & (hs300_df.index <= global_end_date)]
            if not bp.empty:
                bn = bp['benchmark_nav'] / bp['benchmark_nav'].iloc[0]
                ax.plot(bn.index, bn.values, 'k--', label=BENCHMARK_NAME, linewidth=2.5, zorder=10)
        colors = plt.cm.tab10(np.linspace(0, 1, 10))
        for i, (code, grp) in enumerate(df_plot.groupby('FundCode')):
            lbl = f"{code} {code_to_name.get(code, '')[:8]}"
            nv = grp['NAV'] / grp['NAV'].iloc[0]
            ax.plot(grp['Date'], nv, label=lbl, color=colors[i%10], linewidth=1.5, alpha=0.9)
        ax.set_title('Top 10 基金累计净值走势', fontsize=16, pad=15)
        ax.set_ylabel('累计净值', fontsize=12)
        ax.legend(loc='upper left', bbox_to_anchor=(0, 1), ncol=2, fontsize=9, frameon=False, borderaxespad=0.)
        ax.grid(True, alpha=0.3, linestyle='--')
        ax.set_axisbelow(True)
        safe_save(fig, 3, "净值走势")
    except Exception as e:
        pass

    # Page 4: 动态收益对比
    try:
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        axes = axes.flatten()
        top10_codes = results_sorted.head(10)['基金代码'].tolist()
        periods = [365, 730, 1095, 1825]
        colors = plt.cm.tab10(np.linspace(0, 1, 10))
        for idx, days in enumerate(periods):
            ax = axes[idx]
            end_d = df['Date'].max()
            start_d = end_d - timedelta(days=days)
            mask = (df['Date'] >= start_d) & (df['Date'] <= end_d)
            sub_df = df[mask]
            for i, code in enumerate(top10_codes):
                cd = sub_df[sub_df['FundCode']==code].sort_values('Date')
                if len(cd) < 2:
                    continue
                nv = cd['NAV'].values
                ret = (nv / nv[0] - 1) * 100
                ax.plot(cd['Date'], ret, label=code, color=colors[i%10], linewidth=1.5)
            if hs300_df is not None:
                bp = hs300_df[(hs300_df.index >= start_d) & (hs300_df.index <= end_d)]
                if len(bp) > 1:
                    bn = (bp['benchmark_nav'] / bp['benchmark_nav'].iloc[0] - 1) * 100
                    ax.plot(bp.index, bn, 'k--', label='沪深300指数', alpha=0.6, linewidth=2)
            ax.set_title(f'近{days//30}月累计收益对比 (Top 10)', fontsize=14)
            ax.grid(True, alpha=0.3)
            ax.legend(fontsize=7, loc='upper left', ncol=2)
            ax.set_ylim(bottom=min(-20, ax.get_ylim()[0]))
            ax.set_ylabel('累计收益率 (%)', fontsize=11)
        plt.suptitle('Top 10 基金多周期动态收益对比', fontsize=18, fontweight='bold', y=1.02)
        plt.tight_layout(rect=[0, 0.03, 1, 0.96])
        safe_save(fig, 4, "动态对比")
    except Exception as e:
        pass

    # Page 5: 夏普比率气泡图
    try:
        fig, ax = plt.subplots(figsize=(10, 6))
        data = results_sorted.copy()
        data = data[data['夏普比率'].notna() & data['年化波动率'].notna() & data['年化收益率'].notna()]
        if len(data) > 0:
            x = data['年化波动率']
            y = data['年化收益率']
            z = data['夏普比率']
            z_norm = (z - z.min()) / (z.max() - z.min() + 1e-9)
            sizes = z_norm * 550 + 50
            scatter = ax.scatter(x, y, s=sizes, c=z, cmap='RdYlGn', alpha=0.6, edgecolors='k', linewidth=0.5)
            top3 = data.nlargest(3, '夏普比率')
            bottom3 = data.nsmallest(3, '夏普比率')
            label_indices = list(top3.index) + list(bottom3.index)
            for idx in label_indices:
                is_top = idx in top3.index
                color = '#155724' if is_top else '#721c24'
                va_pos = 'bottom' if is_top else 'top'
                ax.text(x.loc[idx], y.loc[idx], f" {data.loc[idx, '基金代码']}",
                       fontsize=10, fontweight='bold', ha='left', va=va_pos, color=color,
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8, edgecolor='none'))
            ax.axhline(y=RISK_FREE_RATE, color='gray', linestyle='--', linewidth=1.5,
                      label=f'无风险利率 ({RISK_FREE_RATE:.1%})')
            ax.set_title('夏普比率深度分析 (标注 Top3 & Bottom3)', fontsize=16, pad=15)
            ax.set_xlabel('年化波动率 (风险)', fontsize=12)
            ax.set_ylabel('年化收益率 (收益)', fontsize=12)
            ax.grid(True, alpha=0.3)
            cbar = plt.colorbar(scatter, ax=ax)
            cbar.set_label('夏普比率', fontsize=12)
            ax.legend(loc='lower right')
        else:
            ax.text(0.5, 0.5, "无有效夏普比率数据", ha='center', transform=ax.transAxes, fontsize=16)
        plt.tight_layout(rect=[0, 0.08, 1, 1])
        safe_save(fig, 5, "夏普气泡图")
    except Exception as e:
        pass

    # Page 6: 风险收益分布散点图
    try:
        fig, ax = plt.subplots(figsize=(10, 7))
        x = results_sorted["年化波动率"]
        y = results_sorted["年化收益率"]
        if results_sorted['信息比率'].notna().any():
            c_data = results_sorted["信息比率"]
            cmap = 'RdYlGn'
            cbar_label = '信息比率'
            label_sort_col = "信息比率"
        else:
            c_data = results_sorted["夏普比率"]
            cmap = 'viridis'
            cbar_label = '夏普比率'
            label_sort_col = "夏普比率"
        sc = ax.scatter(x, y, c=c_data, cmap=cmap, s=80, alpha=0.7, edgecolors='k', linewidth=0.5)
        valid_data = results_sorted[results_sorted[label_sort_col].notna()]
        if not valid_data.empty:
            top3 = valid_data.nlargest(3, label_sort_col)
            bottom3 = valid_data.nsmallest(3, label_sort_col)
            label_indices = list(top3.index) + list(bottom3.index)
            for idx in label_indices:
                is_top = idx in top3.index
                color = '#155724' if is_top else '#721c24'
                va_pos = 'bottom' if is_top else 'top'
                ax.text(valid_data.loc[idx, '年化波动率'], valid_data.loc[idx, '年化收益率'],
                       f" {valid_data.loc[idx, '基金代码']}", fontsize=10, fontweight='bold',
                       ha='left', va=va_pos, color=color,
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8, edgecolor='none'))
        ax.set_title(f'风险收益分布散点图 (标注{label_sort_col} Top3 & Bottom3)', fontsize=18, fontweight='bold', pad=15)
        ax.set_xlabel('年化波动率', fontsize=12)
        ax.set_ylabel('年化收益率', fontsize=12)
        ax.grid(True, alpha=0.3)
        cbar = plt.colorbar(sc, ax=ax, label=cbar_label)
        cbar.set_label(cbar_label, fontsize=12, rotation=270, labelpad=15)
        plt.tight_layout(rect=[0, 0.08, 1, 1])
        safe_save(fig, 6, "风险收益分布")
    except Exception as e:
        pass

    # Page 7: 信息比率 vs 跟踪误差
    try:
        fig, ax = plt.subplots(figsize=(10, 7))
        ir_data = results_sorted[results_sorted['信息比率'].notna()]
        if not ir_data.empty:
            sc = ax.scatter(ir_data['跟踪误差'], ir_data['信息比率'], c=ir_data['信息比率'],
                         cmap='RdYlGn', s=80, edgecolors='k', linewidth=0.5)
            top3 = ir_data.nlargest(3, '信息比率')
            bottom3 = ir_data.nsmallest(3, '信息比率')
            label_indices = list(top3.index) + list(bottom3.index)
            for idx in label_indices:
                is_top = idx in top3.index
                color = '#155724' if is_top else '#721c24'
                va_pos = 'bottom' if is_top else 'top'
                ax.text(ir_data.loc[idx, '跟踪误差'], ir_data.loc[idx, '信息比率'],
                       f" {ir_data.loc[idx, '基金代码']}", fontsize=10, fontweight='bold',
                       ha='left', va=va_pos, color=color,
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8, edgecolor='none'))
            ax.axhline(0, color='gray', linestyle='-', linewidth=1.5)
            ax.axvline(0, color='gray', linestyle='-', linewidth=1.5, alpha=0.3)
            ax.set_title('信息比率 vs 跟踪误差 (标注 Top3 & Bottom3)', fontsize=18, fontweight='bold', pad=15)
            ax.set_xlabel('跟踪误差', fontsize=12)
            ax.set_ylabel('信息比率', fontsize=12)
            ax.grid(True, alpha=0.3)
            cbar = plt.colorbar(sc, ax=ax, label='信息比率')
            cbar.set_label('信息比率', fontsize=12, rotation=270, labelpad=15)
        else:
            ax.text(0.5, 0.5, "无有效信息比率数据", ha='center', transform=ax.transAxes, fontsize=16)
            ax.set_title('信息比率分析', fontsize=18, fontweight='bold')
        plt.tight_layout(rect=[0, 0.08, 1, 1])
        safe_save(fig, 7, "信息比率分析")
    except Exception as e:
        pass

    # Page 8: Top 10 深度明细表
    try:
        fig, ax = plt.subplots(figsize=(18, 9))
        ax.axis('off')
        display_count = min(10, len(results_sorted))
        top_n_data = results_sorted.head(display_count).copy()
        target_cols = [
            "序号", "基金代码", "基金名称", "年限",
            "累计收益率", "年化收益率", "年化波动率", "最大回撤",
            "夏普比率", "索提诺比率", "卡玛比率",
            "信息比率", "年化超额收益", "跟踪误差",
            "胜率", "盈亏比"
        ]
        final_rows = []
        for i, (_, row) in enumerate(top_n_data.iterrows()):
            new_row = {"序号": i + 1}
            for col in target_cols:
                if col != "序号":
                    new_row[col] = row[col] if col in row else None
            final_rows.append(new_row)
        current_rows = len(final_rows)
        if current_rows < 10:
            for k in range(10 - current_rows):
                empty_row = {col: '-' for col in target_cols}
                empty_row["序号"] = '-'
                final_rows.append(empty_row)
        mean_row_top = {"序号": "-"}
        for col in target_cols:
            if col == "序号":
                continue
            if col == "基金代码":
                mean_row_top[col] = f"TOP{display_count}均值"
            elif col == "基金名称":
                mean_row_top[col] = "-"
            else:
                if col in top_n_data.columns:
                    numeric_col = top_n_data[col]
                    mean_val = numeric_col.mean() if pd.api.types.is_numeric_dtype(numeric_col) else 0
                    mean_row_top[col] = mean_val
                else:
                    mean_row_top[col] = "-"
        mean_row_all = {"序号": "-"}
        for col in target_cols:
            if col == "序号":
                continue
            if col == "基金代码":
                mean_row_all[col] = "全部均值"
            elif col == "基金名称":
                mean_row_all[col] = "-"
            else:
                if col in results_sorted.columns:
                    numeric_col = results_sorted[col]
                    mean_val = numeric_col.mean() if pd.api.types.is_numeric_dtype(numeric_col) else 0
                    mean_row_all[col] = mean_val
                else:
                    mean_row_all[col] = "-"
        final_rows.append(mean_row_top)
        final_rows.append(mean_row_all)
        final_df = pd.DataFrame(final_rows)
        display_cols = [c for c in target_cols if c in final_df.columns]
        def fmt_val(v, col):
            if col == "序号":
                return '-' if v == '-' else str(int(v))
            if col in ["基金代码", "基金名称"]:
                return str(v)
            if v == '-':
                return '-'
            if pd.isna(v):
                return "-"
            if col in ["年化波动率", "累计收益率"]:
                return f"{v:.2%}"
            elif any(x in col for x in ["收益率", "回撤", "胜率", "误差", "超额"]):
                return f"{v:.2%}"
            elif any(x in col for x in ["比率", "年限", "盈亏"]):
                return f"{v:.2f}"
            else:
                return str(v)
        for col in final_df.columns:
            final_df[col] = final_df[col].apply(lambda x: fmt_val(x, col))
        table = ax.table(cellText=final_df.values, colLabels=final_df.columns, loc='center', cellLoc='center')
        table.auto_set_font_size(False)
        table.set_fontsize(8.5)
        table.scale(1, 1.3)
        n_real_funds = display_count
        for (r, c), cell in table.get_celld().items():
            col_name = display_cols[c]
            cell.set_facecolor('#FFFFFF')
            cell.set_edgecolor('#DDDDDD')
            cell.set_text_props(color='black', fontweight='normal')
            if r == 0:
                cell.set_facecolor('#2E75B6')
                cell.set_text_props(color='white', fontweight='bold')
                cell.set_edgecolor('#1a5c9e')
            elif r == 11:
                cell.set_facecolor('#FFF3CD')
                cell.set_text_props(color='#856404', fontweight='bold')
                cell.set_edgecolor('#FFEBA6')
            elif r == 12:
                cell.set_facecolor('#D4EDDA')
                cell.set_text_props(color='#155724', fontweight='bold')
                cell.set_edgecolor('#C3E6CB')
            elif 1 <= r <= 10:
                if r <= n_real_funds:
                    if r % 2 == 1:
                        cell.set_facecolor('#F8F9FA')
                    if col_name == "年化收益率":
                        cell.set_facecolor('#DFF0D8')
                    if col_name == "最大回撤" and r-1 < len(top_n_data):
                        original_val = top_n_data.iloc[r-1][col_name] if col_name in top_n_data.columns else None
                        if pd.notna(original_val) and isinstance(original_val, (int, float)) and original_val > 0.20:
                            cell.set_facecolor('#F8D7DA')
                else:
                    cell.set_facecolor('#F9F9F9')
                    cell.set_text_props(color='#AAAAAA')
        ax.set_title(f"Top 10 基金深度绩效明细表 (按年化收益率排序)", fontsize=16, fontweight='bold', pad=20)
        plt.tight_layout()
        safe_save(fig, 8, "Top10 明细表")
    except Exception as e:
        pass

    # Page 9: 深度分析解读
    try:
        fig = plt.figure(figsize=(8.27, 11.69))
        ax = fig.add_axes([0, 0, 1, 1])
        ax.axis('off')
        ax.text(0.5, 0.94, "Top 10 基金深度分析解读", ha='center', va='top',
                fontsize=24, fontweight='bold', color='#2E75B6', transform=ax.transAxes)
        ax.plot([0.3, 0.7], [0.90, 0.90], color='#2E75B6', linewidth=2, transform=ax.transAxes)
        top10 = results_sorted.head(10).copy()
        best_return_idx = top10['年化收益率'].idxmax()
        best_return_fund = top10.loc[best_return_idx]
        best_risk_idx = top10['最大回撤'].idxmin()
        best_risk_fund = top10.loc[best_risk_idx]
        best_sharpe_idx = top10['夏普比率'].idxmax()
        best_sharpe_fund = top10.loc[best_sharpe_idx]
        has_ir = False
        best_ir_fund = None
        if top10['信息比率'].notna().any():
            valid_ir = top10[top10['信息比率'].notna()]
            if not valid_ir.empty:
                best_ir_idx = valid_ir['信息比率'].idxmax()
                best_ir_fund = top10.loc[best_ir_idx]
                has_ir = True
        worst_vol_idx = top10['年化波动率'].idxmax()
        worst_vol_fund = top10.loc[worst_vol_idx]
        worst_dd_idx = top10['最大回撤'].idxmax()
        worst_dd_fund = top10.loc[worst_dd_idx]
        align_x = 0.10
        curr_y = 0.85
        line_height = 0.055
        font_title = 14
        font_text = 12
        def draw_block(title, content_lines, y_start, title_color='#2E75B6', is_bold_title=False):
            weight = 'bold' if is_bold_title else 'bold'
            ax.text(align_x, y_start, title, ha='left', va='top', fontsize=font_title,
                   fontweight=weight, color=title_color, transform=ax.transAxes)
            current_y = y_start - 0.035
            for line in content_lines:
                ax.text(align_x, current_y, line, ha='left', va='top', fontsize=font_text,
                       color='#333333', transform=ax.transAxes, wrap=True)
                current_y -= line_height
            return current_y
        ir_line = ""
        if has_ir and best_ir_fund is not None:
            ir_line = f"4. 超额之星：{best_ir_fund['基金名称']} ({best_ir_fund['基金代码']})，信息比率 {best_ir_fund['信息比率']:.2f}，战胜基准能力稳定。"
        curr_y = draw_block(
            "核心亮点",
            [
                f"1. 收益冠军：{best_return_fund['基金名称']} ({best_return_fund['基金代码']})，年化收益率高达 {best_return_fund['年化收益率']:.2%}，盈利能力最强。",
                f"2. 性价比之王：{best_sharpe_fund['基金名称']} ({best_sharpe_fund['基金代码']})，夏普比率 {best_sharpe_fund['夏普比率']:.2f}，单位风险回报最优。",
                f"3. 风控标杆：{best_risk_fund['基金名称']} ({best_risk_fund['基金代码']})，最大回撤仅 {best_risk_fund['最大回撤']:.2%}，抗跌能力出色。",
                ir_line
            ],
            curr_y
        )
        curr_y -= 0.02
        curr_y = draw_block(
            "风险提示",
            [
                f"1. 高波动警示：{worst_vol_fund['基金名称']} 年化波动率 {worst_vol_fund['年化波动率']:.2%}，净值起伏较大。",
                f"2. 深回撤警示：{worst_dd_fund['基金名称']} 历史最大回撤 {worst_dd_fund['最大回撤']:.2%}，需注意持有体验。"
            ],
            curr_y,
            title_color='#D9534F'
        )
        curr_y -= 0.02
        avg_ret = top10['年化收益率'].mean()
        avg_dd = top10['最大回撤'].mean()
        avg_sharpe = top10['夏普比率'].mean()
        comment_line3 = f'建议投资者根据自身风险偏好，在\"收益冠军\"与\"风控标杆\"之间进行均衡配置。'
        curr_y = draw_block(
            "综合点评",
            [
                f"Top 10 基金整体表现优异，平均年化收益率 {avg_ret:.2%}，平均夏普比率 {avg_sharpe:.2f}。",
                f"虽然部分基金波动较大（平均最大回撤 {avg_dd:.2%}），但头部基金在收益与风险的平衡上表现出色。",
                comment_line3
            ],
            curr_y,
            title_color='#800080',
            is_bold_title=True
        )
        safe_save(fig, 9, "深度分析解读")
    except Exception as e:
        pass

    # Page 10: 附录
    try:
        fig = plt.figure(figsize=(8.27, 11.69))
        ax = fig.add_axes([0, 0, 1, 1])
        ax.axis('off')
        ax.text(0.5, 0.92, "附录一：核心指标说明", ha='center', va='top',
                fontsize=24, fontweight='bold', color='#2E75B6', transform=ax.transAxes)
        ax.plot([0.3, 0.7], [0.88, 0.88], color='#2E75B6', linewidth=2, transform=ax.transAxes)
        metrics_desc = [
            ("1. 年化收益率", "反映基金在一年内的平均收益水平，是衡量基金盈利能力的核心指标。数值越高越好。"),
            ("2. 年化波动率", "衡量基金净值的波动程度，代表投资风险。数值越低，表现越稳定。"),
            ("3. 最大回撤", "在选定周期内任一历史时点往后推，产品净值走到最低点时的收益率回撤幅度的最大值。衡量极端风险，越小越好。"),
            ("4. 夏普比率", "衡量每承担一单位总风险所产生的超额回报。数值越大，表示在相同风险下获得的收益越高。通常大于 1 为优秀。"),
            ("5. 索提诺比率", "类似夏普比率，但只考虑下行风险（亏损波动）。更适合关注避免亏损的投资者。"),
            ("6. 卡玛比率", "年化收益率与最大回撤的比值。衡量收益与极端风险的性价比，越高越好。"),
            ("7. 信息比率", "衡量基金相对于基准指数的超额收益能力及其稳定性。数值越大，战胜基准的能力越强。"),
            ("8. 胜率", "统计周期内获得正收益的天数占比。反映盈利的频率。"),
            ("9. 盈亏比", "平均每次盈利金额与平均每次亏损金额的比值。反映盈利的质量。"),
            ("10. 跟踪误差", "基金收益率与基准收益率之间差异的波动程度。衡量基金偏离基准的程度。")
        ]
        start_x = 0.15
        start_y = 0.82
        line_height = 0.075
        font_size_title = 14
        font_size_desc = 12
        for i, (title, desc) in enumerate(metrics_desc):
            y_pos = start_y - i * line_height
            if y_pos < 0.15:
                break
            ax.text(start_x, y_pos, title, ha='left', va='top', fontsize=font_size_title,
                   fontweight='bold', color='#333333', transform=ax.transAxes)
            desc_y = y_pos - 0.035
            ax.text(start_x, desc_y, desc, ha='left', va='top', fontsize=font_size_desc,
                   color='#555555', transform=ax.transAxes, wrap=True)
        ax.text(0.5, 0.05, DISCLAIMER_TEXT, ha='center', va='center',
               fontsize=10, color='#999999', style='italic', transform=ax.transAxes)
        safe_save(fig, 10, "附录")
    except Exception as e:
        pass

    pdf.close()
    output_buffer.seek(0)
    return output_buffer.getvalue()


# ================= 主程序 =================
st.markdown('<div class="main-title">📊 基金绩效深度分析系统</div>', unsafe_allow_html=True)

# ========== 阶段1: 未上传文件 ==========
if uploaded_file is None:
    st.info("👈 请在左侧上传 CSV 文件开始分析")
    st.markdown("""
    ### 📋 使用说明
    1. 在左侧上传包含基金净值数据的 CSV 文件
    2. 系统支持多种列名格式（JJDM/FundCode/基金代码、DATE1/Date/日期、NAV1/NAV/单位净值）
    3. 可调整年交易天数、无风险利率、最小年限等参数
    4. 点击 **开始计算** 按钮后生成完整分析报告
    5. 分析完成后可导出与桌面版一致的 PDF 报告

    ### 📊 分析内容
    - 累计净值走势（Top 10）
    - 多周期动态收益对比（1年/2年/3年/5年）
    - 夏普比率气泡图
    - 风险收益分布散点图
    - 信息比率 vs 跟踪误差
    - Top 10 基金深度绩效明细表
    - 深度分析解读与风险提示
    - 核心指标说明附录
    """)
    st.stop()

# ========== 阶段2: 已上传文件，先读取并预览 ==========
if uploaded_file is not None and st.session_state.raw_df is None:
    with st.spinner("🔄 正在读取基金数据..."):
        raw_df = load_and_clean_data(uploaded_file.getvalue())
        if raw_df is not None and not raw_df.empty:
            st.session_state.raw_df = raw_df
            st.session_state.file_stem = uploaded_file.name.replace('.csv', '').replace('(', '_').replace(')', '_')
            st.session_state.code_to_name = raw_df.groupby('FundCode')['FundName'].first().to_dict()
            st.session_state.global_start_date = raw_df['Date'].min()
            st.session_state.global_end_date = raw_df['Date'].max()
            st.rerun()
        else:
            st.error("❌ 数据读取失败，请检查文件格式。")
            st.stop()

# ========== 阶段3: 显示数据预览和计算按钮 ==========
if st.session_state.raw_df is not None and not st.session_state.calc_done:
    raw_df = st.session_state.raw_df

    st.success(f"✅ 文件读取成功！共 {len(raw_df)} 条记录，{raw_df['FundCode'].nunique()} 只基金")

    # 数据预览
    with st.expander("📋 数据预览（前20行）", expanded=True):
        st.dataframe(raw_df.head(20), use_container_width=True)

    # 基本信息展示
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("基金数量", f"{raw_df['FundCode'].nunique()} 只")
    with col2:
        st.metric("总记录数", f"{len(raw_df)} 条")
    with col3:
        st.metric("业绩基准", BENCHMARK_NAME)

    # 日期区间单独一行显示
    preview_date_range = f"{st.session_state.global_start_date.strftime('%Y-%m-%d')} 至 {st.session_state.global_end_date.strftime('%Y-%m-%d')}"
    preview_days = (st.session_state.global_end_date - st.session_state.global_start_date).days
    st.markdown(f"""
    <div style="background-color:#E8F4FD; padding:12px 20px; border-radius:8px; border-left:4px solid #2E75B6; margin:10px 0;">
        <span style="font-size:16px; color:#333;">📅 <strong>数据区间</strong>：{preview_date_range}</span>
        <span style="font-size:14px; color:#666; margin-left:20px;">（共 {preview_days} 天）</span>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # 配置确认
    st.subheader("⚙️ 当前分析配置")
    cfg_col1, cfg_col2, cfg_col3, cfg_col4 = st.columns(4)
    with cfg_col1:
        st.info(f"**年交易天数**: {TRADING_DAYS_PER_YEAR}")
    with cfg_col2:
        st.info(f"**无风险利率**: {RISK_FREE_RATE:.2%}")
    with cfg_col3:
        st.info(f"**最小年限**: {MIN_YEARS_REQUIRED} 年")
    with cfg_col4:
        st.info(f"**基准代码**: {BENCHMARK_CODE}")

    st.caption("💡 如需修改配置，请在左侧边栏调整参数后，点击下方按钮重新计算")

    st.divider()

    # 计算按钮（核心交互点）
    st.markdown("""
    <div style="text-align: center; padding: 20px;">
        <h3>🚀 准备就绪，点击下方按钮开始计算</h3>
    </div>
    """, unsafe_allow_html=True)

    btn_col1, btn_col2, btn_col3 = st.columns([1, 2, 1])
    with btn_col2:
        calc_clicked = st.button("🧮 开始计算绩效指标", type="primary", use_container_width=True, 
                                  key="btn_start_calc", help="点击后将计算所有基金的绩效指标并生成分析报告")

    if calc_clicked:
        # ========== 阶段4: 执行计算 ==========
        progress_bar = st.progress(0, text="正在初始化...")

        # 步骤1: 获取基准数据
        progress_bar.progress(10, text="🌐 正在获取基准数据...")
        hs300_df = get_benchmark_data(BENCHMARK_CODE)
        st.session_state.hs300_df = hs300_df
        if hs300_df is not None:
            st.success(f"✅ 基准数据加载成功：{len(hs300_df)} 条")
        else:
            st.warning("⚠️ 基准数据获取失败，信息比率等指标将无法计算")

        # 步骤2: 计算所有基金指标
        progress_bar.progress(30, text="🧮 正在计算全量基金指标...")
        bench_series = hs300_df['benchmark_nav'] if hs300_df is not None else None
        results_df = raw_df.groupby('FundCode').apply(
            lambda x: calculate_metrics(x, bench_series)
        ).reset_index(drop=True)

        progress_bar.progress(60, text="📊 正在筛选和排序...")
        results_filtered = results_df[results_df['年限'] > MIN_YEARS_REQUIRED].reset_index(drop=True)

        if results_filtered.empty:
            st.error("❌ 没有满足年限要求的基金。请调整最小年限参数。")
            st.stop()

        results_sorted = results_filtered.sort_values(
            by='年化收益率', ascending=False, na_position='last'
        ).reset_index(drop=True)

        st.session_state.results_sorted = results_sorted
        st.session_state.calc_done = True

        progress_bar.progress(100, text="✅ 计算完成！")
        st.success(f"✅ 计算完成，有效基金：{len(results_sorted)} 只")
        st.rerun()

# ========== 阶段5: 显示计算结果（所有Tab）==========
if st.session_state.calc_done and st.session_state.results_sorted is not None:
    raw_df = st.session_state.raw_df
    results_sorted = st.session_state.results_sorted
    hs300_df = st.session_state.hs300_df
    global_start_date = st.session_state.global_start_date
    global_end_date = st.session_state.global_end_date
    code_to_name = st.session_state.code_to_name

    # 报告头部信息
    st.divider()
    st.subheader("📊 分析结果概览")

    # 使用卡片式布局，日期区间独占一行避免截断
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("有效基金数", f"{len(results_sorted)} 只")
    with col2:
        st.metric("业绩基准", BENCHMARK_NAME)
    with col3:
        st.metric("无风险利率", f"{RISK_FREE_RATE:.2%}")

    # 日期区间单独一行，使用自定义HTML卡片确保完整显示
    date_range_str = f"{global_start_date.strftime('%Y-%m-%d')} 至 {global_end_date.strftime('%Y-%m-%d')}"
    days_count = (global_end_date - global_start_date).days
    st.markdown(f"""
    <div style="background-color:#E8F4FD; padding:12px 20px; border-radius:8px; border-left:4px solid #2E75B6; margin:10px 0;">
        <span style="font-size:16px; color:#333;">📅 <strong>分析区间</strong>：{date_range_str}</span>
        <span style="font-size:14px; color:#666; margin-left:20px;">（共 {days_count} 天）</span>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # ================= Tab 布局 =================
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
        "📈 净值走势", "📊 多周期收益", "🫧 夏普气泡图", "⚡ 风险收益分布",
        "📐 信息比率", "📋 绩效明细", "📝 深度解读", "📖 指标说明"
    ])

    # --- Tab 1: 累计净值走势 ---
    with tab1:
        st.subheader("Top 10 基金累计净值走势")
        fig1, ax1 = plt.subplots(figsize=(14, 7))
        top_codes = results_sorted.head(10)["基金代码"].tolist()
        df_plot = raw_df[raw_df['FundCode'].isin(top_codes)]

        if hs300_df is not None:
            bp = hs300_df[(hs300_df.index >= global_start_date) & (hs300_df.index <= global_end_date)]
            if not bp.empty:
                bn = bp['benchmark_nav'] / bp['benchmark_nav'].iloc[0]
                ax1.plot(bn.index, bn.values, 'k--', label=BENCHMARK_NAME, linewidth=2.5, zorder=10)

        colors = plt.cm.tab10(np.linspace(0, 1, 10))
        for i, (code, grp) in enumerate(df_plot.groupby('FundCode')):
            lbl = f"{code} {code_to_name.get(code, '')[:8]}"
            nv = grp['NAV'] / grp['NAV'].iloc[0]
            ax1.plot(grp['Date'], nv, label=lbl, color=colors[i%10], linewidth=1.5, alpha=0.9)

        ax1.set_title('Top 10 基金累计净值走势', fontsize=16, pad=15)
        ax1.set_ylabel('累计净值', fontsize=12)
        ax1.legend(loc='upper left', bbox_to_anchor=(0, 1), ncol=2, fontsize=9, frameon=False, borderaxespad=0.)
        ax1.grid(True, alpha=0.3, linestyle='--')
        ax1.set_axisbelow(True)
        st.pyplot(fig1)

    # --- Tab 2: 多周期动态收益对比 ---
    with tab2:
        st.subheader("Top 10 基金多周期动态收益对比")
        fig2, axes = plt.subplots(2, 2, figsize=(14, 10))
        axes = axes.flatten()
        top10_codes = results_sorted.head(10)['基金代码'].tolist()
        periods = [365, 730, 1095, 1825]
        colors = plt.cm.tab10(np.linspace(0, 1, 10))

        for idx, days in enumerate(periods):
            ax = axes[idx]
            end_d = raw_df['Date'].max()
            start_d = end_d - timedelta(days=days)
            mask = (raw_df['Date'] >= start_d) & (raw_df['Date'] <= end_d)
            sub_df = raw_df[mask]

            for i, code in enumerate(top10_codes):
                cd = sub_df[sub_df['FundCode']==code].sort_values('Date')
                if len(cd) < 2:
                    continue
                nv = cd['NAV'].values
                ret = (nv / nv[0] - 1) * 100
                ax.plot(cd['Date'], ret, label=code, color=colors[i%10], linewidth=1.5)

            if hs300_df is not None:
                bp = hs300_df[(hs300_df.index >= start_d) & (hs300_df.index <= end_d)]
                if len(bp) > 1:
                    bn = (bp['benchmark_nav'] / bp['benchmark_nav'].iloc[0] - 1) * 100
                    ax.plot(bp.index, bn, 'k--', label='沪深300指数', alpha=0.6, linewidth=2)

            ax.set_title(f'近{days//30}月累计收益对比 (Top 10)', fontsize=14)
            ax.grid(True, alpha=0.3)
            ax.legend(fontsize=7, loc='upper left', ncol=2)
            ax.set_ylim(bottom=min(-20, ax.get_ylim()[0]))
            ax.set_ylabel('累计收益率 (%)', fontsize=11)

        plt.suptitle('Top 10 基金多周期动态收益对比', fontsize=18, fontweight='bold', y=1.02)
        plt.tight_layout(rect=[0, 0.03, 1, 0.96])
        st.pyplot(fig2)

    # --- Tab 3: 夏普比率气泡图 ---
    with tab3:
        st.subheader("夏普比率深度分析")
        fig3, ax3 = plt.subplots(figsize=(12, 7))
        data = results_sorted.copy()
        data = data[data['夏普比率'].notna() & data['年化波动率'].notna() & data['年化收益率'].notna()]

        if len(data) > 0:
            x = data['年化波动率']
            y = data['年化收益率']
            z = data['夏普比率']
            z_norm = (z - z.min()) / (z.max() - z.min() + 1e-9)
            sizes = z_norm * 550 + 50
            scatter = ax3.scatter(x, y, s=sizes, c=z, cmap='RdYlGn', alpha=0.6, edgecolors='k', linewidth=0.5)

            top3 = data.nlargest(3, '夏普比率')
            bottom3 = data.nsmallest(3, '夏普比率')
            label_indices = list(top3.index) + list(bottom3.index)
            for idx in label_indices:
                is_top = idx in top3.index
                color = '#155724' if is_top else '#721c24'
                va_pos = 'bottom' if is_top else 'top'
                ax3.text(x.loc[idx], y.loc[idx], f" {data.loc[idx, '基金代码']}", 
                       fontsize=10, fontweight='bold', ha='left', va=va_pos, color=color,
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8, edgecolor='none'))

            ax3.axhline(y=RISK_FREE_RATE, color='gray', linestyle='--', linewidth=1.5, 
                       label=f'无风险利率 ({RISK_FREE_RATE:.1%})')
            ax3.set_title('夏普比率深度分析 (标注 Top3 & Bottom3)', fontsize=16, pad=15)
            ax3.set_xlabel('年化波动率 (风险)', fontsize=12)
            ax3.set_ylabel('年化收益率 (收益)', fontsize=12)
            ax3.grid(True, alpha=0.3)
            cbar = plt.colorbar(scatter, ax=ax3)
            cbar.set_label('夏普比率', fontsize=12)
            ax3.legend(loc='lower right')
        else:
            ax3.text(0.5, 0.5, "无有效夏普比率数据", ha='center', transform=ax3.transAxes, fontsize=16)

        plt.tight_layout(rect=[0, 0.08, 1, 1])
        st.pyplot(fig3)

    # --- Tab 4: 风险收益分布散点图 ---
    with tab4:
        st.subheader("风险收益分布散点图")
        fig4, ax4 = plt.subplots(figsize=(12, 7))
        x = results_sorted["年化波动率"]
        y = results_sorted["年化收益率"]

        if results_sorted['信息比率'].notna().any():
            c_data = results_sorted["信息比率"]
            cmap = 'RdYlGn'
            cbar_label = '信息比率'
            label_sort_col = "信息比率"
        else:
            c_data = results_sorted["夏普比率"]
            cmap = 'viridis'
            cbar_label = '夏普比率'
            label_sort_col = "夏普比率"

        sc = ax4.scatter(x, y, c=c_data, cmap=cmap, s=80, alpha=0.7, edgecolors='k', linewidth=0.5)
        valid_data = results_sorted[results_sorted[label_sort_col].notna()]

        if not valid_data.empty:
            top3 = valid_data.nlargest(3, label_sort_col)
            bottom3 = valid_data.nsmallest(3, label_sort_col)
            label_indices = list(top3.index) + list(bottom3.index)
            for idx in label_indices:
                is_top = idx in top3.index
                color = '#155724' if is_top else '#721c24'
                va_pos = 'bottom' if is_top else 'top'
                ax4.text(valid_data.loc[idx, '年化波动率'], valid_data.loc[idx, '年化收益率'], 
                       f" {valid_data.loc[idx, '基金代码']}", fontsize=10, fontweight='bold', 
                       ha='left', va=va_pos, color=color,
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8, edgecolor='none'))

        ax4.set_title(f'风险收益分布散点图 (标注{label_sort_col} Top3 & Bottom3)', 
                     fontsize=18, fontweight='bold', pad=15)
        ax4.set_xlabel('年化波动率', fontsize=12)
        ax4.set_ylabel('年化收益率', fontsize=12)
        ax4.grid(True, alpha=0.3)
        cbar = plt.colorbar(sc, ax=ax4, label=cbar_label)
        cbar.set_label(cbar_label, fontsize=12, rotation=270, labelpad=15)
        plt.tight_layout(rect=[0, 0.08, 1, 1])
        st.pyplot(fig4)

    # --- Tab 5: 信息比率 vs 跟踪误差 ---
    with tab5:
        st.subheader("信息比率 vs 跟踪误差")
        fig5, ax5 = plt.subplots(figsize=(12, 7))
        ir_data = results_sorted[results_sorted['信息比率'].notna()]

        if not ir_data.empty:
            sc = ax5.scatter(ir_data['跟踪误差'], ir_data['信息比率'], c=ir_data['信息比率'], 
                           cmap='RdYlGn', s=80, edgecolors='k', linewidth=0.5)
            top3 = ir_data.nlargest(3, '信息比率')
            bottom3 = ir_data.nsmallest(3, '信息比率')
            label_indices = list(top3.index) + list(bottom3.index)

            for idx in label_indices:
                is_top = idx in top3.index
                color = '#155724' if is_top else '#721c24'
                va_pos = 'bottom' if is_top else 'top'
                ax5.text(ir_data.loc[idx, '跟踪误差'], ir_data.loc[idx, '信息比率'], 
                       f" {ir_data.loc[idx, '基金代码']}", fontsize=10, fontweight='bold', 
                       ha='left', va=va_pos, color=color,
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8, edgecolor='none'))

            ax5.axhline(0, color='gray', linestyle='-', linewidth=1.5)
            ax5.axvline(0, color='gray', linestyle='-', linewidth=1.5, alpha=0.3)
            ax5.set_title('信息比率 vs 跟踪误差 (标注 Top3 & Bottom3)', fontsize=18, fontweight='bold', pad=15)
            ax5.set_xlabel('跟踪误差', fontsize=12)
            ax5.set_ylabel('信息比率', fontsize=12)
            ax5.grid(True, alpha=0.3)
            cbar = plt.colorbar(sc, ax=ax5, label='信息比率')
            cbar.set_label('信息比率', fontsize=12, rotation=270, labelpad=15)
        else:
            ax5.text(0.5, 0.5, "无有效信息比率数据\n（请确认基准数据已正确加载）", 
                    ha='center', transform=ax5.transAxes, fontsize=16)
            ax5.set_title('信息比率分析', fontsize=18, fontweight='bold')

        plt.tight_layout(rect=[0, 0.08, 1, 1])
        st.pyplot(fig5)

    # --- Tab 6: Top 10 深度绩效明细表 ---
    with tab6:
        st.subheader("Top 10 基金深度绩效明细表")
        display_count = min(10, len(results_sorted))
        top_n_data = results_sorted.head(display_count).copy()

        # 格式化展示
        display_df = top_n_data.copy()
        format_cols = {
            '累计收益率': '{:.2%}', '年化收益率': '{:.2%}', '年化波动率': '{:.2%}',
            '最大回撤': '{:.2%}', '胜率': '{:.2%}', '年化超额收益': '{:.2%}',
            '跟踪误差': '{:.2%}', '夏普比率': '{:.2f}', '索提诺比率': '{:.2f}',
            '卡玛比率': '{:.2f}', '信息比率': '{:.2f}', '盈亏比': '{:.2f}', '年限': '{:.2f}'
        }

        for col, fmt in format_cols.items():
            if col in display_df.columns:
                display_df[col] = display_df[col].apply(lambda x: fmt.format(x) if pd.notna(x) else '-')

        # 添加均值行
        mean_row = {}
        for col in display_df.columns:
            if col in ['基金代码', '基金名称']:
                mean_row[col] = 'TOP10均值'
            elif col in results_sorted.columns and pd.api.types.is_numeric_dtype(results_sorted[col]):
                mean_row[col] = format_cols.get(col, '{:.2f}').format(top_n_data[col].mean()) if col in format_cols else f"{top_n_data[col].mean():.2f}"
            else:
                mean_row[col] = '-'

        all_mean_row = {}
        for col in display_df.columns:
            if col in ['基金代码', '基金名称']:
                all_mean_row[col] = '全部均值'
            elif col in results_sorted.columns and pd.api.types.is_numeric_dtype(results_sorted[col]):
                all_mean_row[col] = format_cols.get(col, '{:.2f}').format(results_sorted[col].mean()) if col in format_cols else f"{results_sorted[col].mean():.2f}"
            else:
                all_mean_row[col] = '-'

        display_df = pd.concat([display_df, pd.DataFrame([mean_row]), pd.DataFrame([all_mean_row])], ignore_index=True)

        # 高亮显示
        def highlight_max_drawdown(val):
            try:
                num = float(val.replace('%', '')) / 100
                if num > 0.20:
                    return 'background-color: #F8D7DA'
            except:
                pass
            return ''

        styled_df = display_df.style.map(highlight_max_drawdown, subset=['最大回撤'])
        st.dataframe(styled_df, use_container_width=True, height=600)

    # --- Tab 7: 深度分析解读 ---
    with tab7:
        st.subheader("Top 10 基金深度分析解读")
        top10 = results_sorted.head(10).copy()

        best_return = top10.loc[top10['年化收益率'].idxmax()]
        best_risk = top10.loc[top10['最大回撤'].idxmin()]
        best_sharpe = top10.loc[top10['夏普比率'].idxmax()]
        worst_vol = top10.loc[top10['年化波动率'].idxmax()]
        worst_dd = top10.loc[top10['最大回撤'].idxmax()]

        has_ir = top10['信息比率'].notna().any()
        best_ir = top10.loc[top10['信息比率'].idxmax()] if has_ir else None

        col_left, col_right = st.columns(2)

        with col_left:
            st.markdown("""
            <div style="background-color:#E8F4FD; padding:15px; border-radius:10px; margin-bottom:10px;">
                <h4 style="color:#2E75B6;">🌟 核心亮点</h4>
            </div>
            """, unsafe_allow_html=True)

            st.success(f"**收益冠军**：{best_return['基金名称']} ({best_return['基金代码']})\n"
                      f"年化收益率高达 **{best_return['年化收益率']:.2%}**，盈利能力最强。")
            st.success(f"**性价比之王**：{best_sharpe['基金名称']} ({best_sharpe['基金代码']})\n"
                      f"夏普比率 **{best_sharpe['夏普比率']:.2f}**，单位风险回报最优。")
            st.success(f"**风控标杆**：{best_risk['基金名称']} ({best_risk['基金代码']})\n"
                      f"最大回撤仅 **{best_risk['最大回撤']:.2%}**，抗跌能力出色。")
            if has_ir and best_ir is not None:
                st.success(f"**超额之星**：{best_ir['基金名称']} ({best_ir['基金代码']})\n"
                          f"信息比率 **{best_ir['信息比率']:.2f}**，战胜基准能力稳定。")

        with col_right:
            st.markdown("""
            <div style="background-color:#FDE8E8; padding:15px; border-radius:10px; margin-bottom:10px;">
                <h4 style="color:#D9534F;">⚠️ 风险提示</h4>
            </div>
            """, unsafe_allow_html=True)

            st.error(f"**高波动警示**：{worst_vol['基金名称']}\n"
                    f"年化波动率 **{worst_vol['年化波动率']:.2%}**，净值起伏较大。")
            st.error(f"**深回撤警示**：{worst_dd['基金名称']}\n"
                    f"历史最大回撤 **{worst_dd['最大回撤']:.2%}**，需注意持有体验。")

        st.divider()

        avg_ret = top10['年化收益率'].mean()
        avg_dd = top10['最大回撤'].mean()
        avg_sharpe = top10['夏普比率'].mean()

        st.markdown(f"""
        <div style="background-color:#F3E8FD; padding:20px; border-radius:10px; border-left:5px solid #800080;">
            <h4 style="color:#800080;">📋 综合点评</h4>
            <p>Top 10 基金整体表现优异，平均年化收益率 <strong>{avg_ret:.2%}</strong>，平均夏普比率 <strong>{avg_sharpe:.2f}</strong>。</p>
            <p>虽然部分基金波动较大（平均最大回撤 {avg_dd:.2%}），但头部基金在收益与风险的平衡上表现出色。</p>
            <p><strong>建议</strong>：投资者应根据自身风险偏好，在收益冠军与风控标杆之间进行均衡配置。</p>
        </div>
        """, unsafe_allow_html=True)

    # --- Tab 8: 核心指标说明 ---
    with tab8:
        st.subheader("附录一：核心指标说明")

        metrics_desc = [
            ("1. 年化收益率", "反映基金在一年内的平均收益水平，是衡量基金盈利能力的核心指标。数值越高越好。"),
            ("2. 年化波动率", "衡量基金净值的波动程度，代表投资风险。数值越低，表现越稳定。"),
            ("3. 最大回撤", "在选定周期内任一历史时点往后推，产品净值走到最低点时的收益率回撤幅度的最大值。衡量极端风险，越小越好。"),
            ("4. 夏普比率", "衡量每承担一单位总风险所产生的超额回报。数值越大，表示在相同风险下获得的收益越高。通常大于 1 为优秀。"),
            ("5. 索提诺比率", "类似夏普比率，但只考虑下行风险（亏损波动）。更适合关注避免亏损的投资者。"),
            ("6. 卡玛比率", "年化收益率与最大回撤的比值。衡量收益与极端风险的性价比，越高越好。"),
            ("7. 信息比率", "衡量基金相对于基准指数的超额收益能力及其稳定性。数值越大，战胜基准的能力越强。"),
            ("8. 胜率", "统计周期内获得正收益的天数占比。反映盈利的频率。"),
            ("9. 盈亏比", "平均每次盈利金额与平均每次亏损金额的比值。反映盈利的质量。"),
            ("10. 跟踪误差", "基金收益率与基准收益率之间差异的波动程度。衡量基金偏离基准的程度。")
        ]

        for title, desc in metrics_desc:
            with st.expander(title):
                st.write(desc)

        st.caption(DISCLAIMER_TEXT)

    # ================= PDF导出按钮 =================
    st.divider()
    st.subheader("📥 导出报告")

    col_pdf, col_csv = st.columns(2)

    with col_pdf:
        generate_pdf_clicked = st.button("📄 生成 PDF 报告", type="primary", use_container_width=True, key="generate_pdf")

        if generate_pdf_clicked:
            with st.spinner("⏳ 正在生成 PDF 报告（约10页）..."):
                try:
                    file_stem = st.session_state.file_stem
                    pdf_bytes = generate_pdf_report(
                        raw_df, results_sorted, hs300_df, 
                        global_start_date, global_end_date, file_stem
                    )
                    st.session_state.pdf_bytes = pdf_bytes
                    st.session_state.pdf_generated = True
                    st.success("✅ PDF 报告生成成功！点击下载按钮获取文件。")
                except Exception as e:
                    st.error(f"❌ PDF 生成失败: {e}")
                    st.exception(e)

        if st.session_state.pdf_generated and st.session_state.pdf_bytes is not None:
            file_stem = st.session_state.file_stem
            st.download_button(
                label="⬇️ 下载 PDF 报告",
                data=st.session_state.pdf_bytes,
                file_name=f"Fund_Performance_Analysis_{file_stem}.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="download_pdf"
            )

    with col_csv:
        csv_buffer = io.StringIO()
        results_sorted.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
        st.download_button(
            label="⬇️ 下载 CSV 数据",
            data=csv_buffer.getvalue(),
            file_name="fund_performance_data.csv",
            mime="text/csv",
            use_container_width=True,
            key="download_csv"
        )