Order of hashes shouldn't matter
Consider this example:
```bash
▶ python hashin.py -r ~/songsearch/requirements.txt --dry-run --update-all
--- Old
+++ New
...
 xmltodict==0.11.0 \
-    --hash=sha256:add07d92089ff611badec526912747cf87afd4f9447af6661aca074eeaf32615 \
-    --hash=sha256:8f8d7d40aa28d83f4109a7e8aa86e67a4df202d9538be40c0cb1d70da527b0df
+    --hash=sha256:8f8d7d40aa28d83f4109a7e8aa86e67a4df202d9538be40c0cb1d70da527b0df \
+    --hash=sha256:add07d92089ff611badec526912747cf87afd4f9447af6661aca074eeaf32615
```

Nothing has actually changed but for some reason, the order of the hashes is different this time. That would cause an unnecessary change.
