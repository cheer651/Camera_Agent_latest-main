# 测试脚本、临时目录、建议清理规则

## 测试与样例文件

- `test.jpg`：图像模型接口测试图片
- `test_alert.py`：飞书推送测试

## 临时目录

这些目录更像调试过程留下的中间产物，不属于主线业务代码：

- `tmpeu58u2nx/`
- `tmp_extractor_probe/`
- `tmp_extractor_test/`
- `tmp_extractor_verify/`
- `_tmp_fallback_verify/`
- `_tmp_postfilter/`
- `_tmp_postfilter_2/`
- `_tmp_replay/`
- `_tmp_replay_cfg/`
- `_tmp_replay_debug/`
- `__pycache__/`

## 建议规则

- 如果后续调试还要保留这些目录，建议统一移到 `tmp/` 或 `debug_artifacts/`
- 如果已经不用，建议只保留必要样例，把可复现的测试逻辑整理成脚本，其余临时输出删除
- `.venv/` 和 `.embed-gpu/` 建议继续保留在项目根目录，但确保 `.gitignore` 不提交它们

