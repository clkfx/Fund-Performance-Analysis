# 基金绩效深度分析系统

基于 Streamlit 的基金绩效分析 Web 应用。

## 功能

- 累计净值走势分析
- 多周期动态收益对比
- 夏普比率气泡图
- 风险收益分布散点图
- 信息比率 vs 跟踪误差
- Top 10 基金深度绩效明细
- 深度分析解读
- PDF 报告导出

## 部署

### Streamlit Cloud (推荐)

1. Fork 本仓库到您的 GitHub 账号
2. 访问 [Streamlit Cloud](https://streamlit.io/cloud)
3. 连接 GitHub 仓库，一键部署

### 本地运行

```bash
pip install -r requirements.txt
streamlit run PAWEB.py
```

## 使用

1. 上传 CSV 文件（包含基金代码、日期、净值列）
2. 调整侧边栏参数（可选）
3. 点击"开始计算绩效指标"
4. 查看分析结果和图表
5. 导出 PDF 报告

## 数据格式

CSV 文件支持以下列名：
- 基金代码: `JJDM`, `FundCode`, `基金代码`
- 日期: `DATE1`, `Date`, `NAV_DATE`, `日期`
- 净值: `NAV1`, `NAV`, `UNIT_NAV`, `单位净值`
