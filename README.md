# 机器人零售的优惠分摊与部分退货冲正资料库

零售原单读取、整数金额检查与借贷核对原语，以及以原销售单为依据的优惠分摊、复式分录生成与核对。 资料在samples，数据语义见docs/domain.md，账簿设计见docs/book.md，本地存档说明见docs/catalog.md。

## 运行

需要Python 3.11以上，仅使用标准库。

```bash
python -m workbench.cli inspect samples
python -m workbench.cli ingest samples state/raw.sqlite3
python -m workbench.cli catalog state/raw.sqlite3
python -m workbench.cli demo state/book.sqlite3
python -m workbench.cli reconcile state/book.sqlite3
python -m unittest discover -s tests -v
python -m compileall -q workbench tests
```

inspect查看文件行数和摘要；ingest将原始包放入SQLite；catalog列出原始包。demo用合成单据演示销售入账、拆退、整退、冲正与幂等重放；reconcile核对账簿并验证实际权益占用。post-sale、return、reverse、entry子命令分别提供单张入账、退货、冲正与分录追溯。测试覆盖已有资料读取、存档幂等、领域原语、账簿流程与多进程并发，compileall检查源码编译。业务计算不会由存档命令自动执行。

## 容器

```bash
docker build -t local-workbench .
docker run --rm --network none local-workbench
docker run --rm --network none local-workbench python -m unittest discover -s tests -v
```

程序不需要外部账号或常驻服务，容器默认查看合成资料。state与output为本地工作目录，不进入版本控制。workbench/io.py负责JSON与文件边界，catalog.py负责原始资料事务，domain.py提供金额原语与分摊规则，book.py负责SQLite事务内的复式账簿，demo.py编排演示场景。
