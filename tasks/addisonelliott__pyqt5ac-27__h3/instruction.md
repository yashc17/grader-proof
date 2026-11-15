Introduce dependency scopes in setup.py
Modern Python modules tend to offer a setup.py that separates dependencies by usage. For example, they provide:
- `core` install (only necessary packages)
- `test` install (the packages you need to run the tests properly)
- `doc` install (the packages you need to build documentation)
- `dev` install (extra packages for development)
- aggregates install tags like `all` (install dependencies from all use-cases)
and the possibility to define extra tags in case of need (like `ci` for extra packages needed on CI only, etc.)

I understand this package has not a lot of dependencies, but I believe it's a good practice to categorize them that way. 

In addition, I'm not entirely sure what the `requirements.txt` is being used for. Currently installing this package with `pip install -e .` works just fine.
