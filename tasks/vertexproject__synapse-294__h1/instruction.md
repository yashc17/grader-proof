delTufo dictionary changed during iteration
```
cli> ask inet:fqdn=woowoowoowoo.com delnode(force=1)
oplog:
    lift (took:0) {'took': 0, 'sub': 0, 'add': 1, 'mnem': 'lift'}
    delnode (took:1) {'excinfo': {'errfile': '/home/autouser/git/synapse/synapse/cores/common.py', 'errline': 2037, 'err': 'RuntimeError', 'errmsg': 'dictionary changed size during iteration'}, 'took': 1, 'sub': 1, 'add': 0, 'mnem': 'delnode'}

options:
    limit = None
    uniq = 1

limits:
    lift = None
    time = None
    touch = None

(0 results)
```
