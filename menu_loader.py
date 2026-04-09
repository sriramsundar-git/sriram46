import json
import os

def load_menu(filepath="menu.json"):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(base_dir, filepath)
    with open(full_path, "r") as f:
        return json.load(f)

def get_menu_dict(menu):
    return {item["item_name"].lower(): item for item in menu}

def get_menu_names(menu):
    names = [item["item_name"].lower() for item in menu]
    return sorted(names, key=len, reverse=True)
