# 可修改内容平台

一个仅使用 Python 标准库构建的轻量内容平台：首页用于展示内容，`/admin` 提供无需代码的编辑界面。

## 运行

```bash
python app.py
```

访问 `http://127.0.0.1:5000` 查看平台，访问 `http://127.0.0.1:5000/admin` 修改平台名称、副标题与内容版块。数据自动保存在 `data/content.json`；该文件在首次访问时创建。

## 测试

```bash
python -m unittest discover -s tests
```
