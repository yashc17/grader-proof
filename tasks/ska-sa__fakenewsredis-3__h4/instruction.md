Mutating operations incorrectly clear expiry
A number of operations modify an existing value, then assign back to `self._db`, which has the side-effect of clearing the expiry time. According to the redis documentation, only operations that completely replace a key (rather than modifying it) clear the expiry. I haven't written any tests yet, but looking at the code, it is probably at least
- decr, incr, incrby, incrbyfloat
- setbit
- ltrim
- rpoplpush

Some other operations where I'm not sure what redis will do
- getset
- rename, renamenx
