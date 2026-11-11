import argparse
import json
import sys
from .io import inspect_bundle,read_json
from .catalog import Catalog
from .book import Book,ConflictError
from . import demo

def main():
    parser=argparse.ArgumentParser(description='业务资料读取、本地存档与复式账簿')
    subs=parser.add_subparsers(dest='command',required=True)
    p=subs.add_parser('inspect');p.add_argument('directory')
    p=subs.add_parser('ingest');p.add_argument('directory');p.add_argument('database')
    p=subs.add_parser('catalog');p.add_argument('database')
    p=subs.add_parser('post-sale');p.add_argument('database');p.add_argument('order')
    p=subs.add_parser('return');p.add_argument('database');p.add_argument('request')
    p=subs.add_parser('reverse');p.add_argument('database');p.add_argument('request')
    p=subs.add_parser('entry');p.add_argument('database');p.add_argument('entry_id',type=int)
    p=subs.add_parser('reconcile');p.add_argument('database')
    p=subs.add_parser('demo');p.add_argument('database');p.add_argument('--samples',default='samples')
    args=parser.parse_args()
    try:
        if args.command=='inspect':result=inspect_bundle(args.directory)
        elif args.command=='ingest':result={'import_id':Catalog(args.database).ingest(args.directory)}
        elif args.command=='catalog':result=Catalog(args.database).summary()
        elif args.command=='post-sale':result=Book(args.database).post_sale(read_json(args.order))
        elif args.command=='return':result=Book(args.database).apply_return(read_json(args.request))
        elif args.command=='reverse':result=Book(args.database).apply_reversal(read_json(args.request))
        elif args.command=='entry':result=Book(args.database).entry(args.entry_id)
        elif args.command=='reconcile':
            result=Book(args.database).reconcile()
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 0 if result['ok'] else 1
        else:result=demo.run(args.database,args.samples)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except ConflictError as exc:
        print(f'请求冲突:{exc}',file=sys.stderr);return 3
    except (ValueError,OSError,KeyError) as exc:
        print(f'处理失败:{exc}',file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
