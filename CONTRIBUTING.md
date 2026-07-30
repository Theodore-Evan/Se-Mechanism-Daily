# 参与贡献

感谢你改进 Se Mechanism Daily。本项目希望保持轻量、可审查，并适合研究者直接 Fork。

## 开始之前

1. Fork 仓库并从 `main` 创建分支。
2. 不要提交 API Key、邮箱、私有数据、绝对本地路径或个人账号。
3. 修改采集器时保持单个来源失败不会中断其他来源。
4. 自动摘要不得把题录中没有的信息写成确定事实。

## 本地检查

```bash
python -m unittest discover -s tests -v
python -m py_compile scripts/collect_papers.py
```

网页修改后，在仓库根目录运行：

```bash
python -m http.server 8000 --directory web
```

检查桌面端和移动端布局，并确认浏览器控制台没有错误。

## Pull Request

请在说明中写清：

- 修改解决了什么问题；
- 是否改变数据格式、环境变量或研究方向配置；
- 执行了哪些测试；
- 是否会增加外部 API 调用或费用。

如果新增文献源，请同时补充失败隔离、去重规则、测试和 README 配置说明。
