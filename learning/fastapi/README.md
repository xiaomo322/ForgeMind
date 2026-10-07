# FastAPI 学习练习

这里保存独立的 FastAPI 练习，不参与 ForgeMind 的默认回归测试。

- `first_route.py`：最初的单路由练习。
- `main.py`：包含创建任务、查询任务和内存状态的进阶练习。
- `test_main.py`：验证 `main.py` 接口和服务行为。

运行进阶练习测试：

```powershell
uv --cache-dir .uv-cache run --no-sync pytest -q -p no:cacheprovider --basetemp=.test-tmp/fastapi-learning learning/fastapi/test_main.py
```
