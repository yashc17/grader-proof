add a disabled trait on the datepicker
I'm currently coding it in a module and the process of disabling a datepicker is uterly boring. I think we could add an extra trait to the layout and pilot the enabling and disabling directly from the built-in widget


```python
self.w_start = sw.DatePicker(label="start", v_model=None)

# disable both the slots (hidden to everyone) and the menu
self.w_start.menu.v_slots[0]["children"].disabled = True
self.w_start.menu.disabled = True
```
