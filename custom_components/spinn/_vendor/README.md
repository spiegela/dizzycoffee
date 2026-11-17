# Vendored `dizzycoffee`

This directory holds a **verbatim copy** of the `dizzycoffee` client from the repo
root, so the Home Assistant integration works when installed via HACS (which ships
only `custom_components/spinn/`, not the top-level `dizzycoffee/` package).

It is a packaging fallback, not a fork: `custom_components/spinn/vendor.py`
prefers a real installed `dizzycoffee` and only adds this copy to `sys.path` when
the library isn't otherwise importable.

Only the modules the integration uses are bundled: `__init__.py`, `api.py`,
`connection.py`, `commands.py`, `recipes.py` (the read path reuses `connection.build` directly,
so `shadow.py`/`cli.py`/`config.py` aren't needed here).

## Re-syncing after changing the real client

Keep these files identical to the originals:

```bash
cp dizzycoffee/{__init__,api,connection,commands,recipes}.py \
   custom_components/spinn/_vendor/dizzycoffee/
```

Verify:

```bash
for f in __init__ api connection commands recipes; do
  diff -q dizzycoffee/$f.py custom_components/spinn/_vendor/dizzycoffee/$f.py
done
```
