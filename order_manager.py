class OrderManager:
    """
    Manages the cart for one customer session.
    menu_dict_getter: a callable that always returns the latest menu dict.
    This ensures items added via admin panel are immediately orderable.
    """

    def __init__(self, menu_dict_getter):
        # Accept a callable so we always get the latest menu on every operation
        self._get_menu = menu_dict_getter
        self.cart = {}

    @property
    def menu_dict(self):
        return self._get_menu()

    def add_item(self, item_name, qty=1):
        item_name = item_name.lower()
        menu = self.menu_dict
        if item_name not in menu:
            return False, f"'{item_name.title()}' is not on our menu."
        item = menu[item_name]
        if not item.get("is_available", True):
            return False, f"Sorry, '{item_name.title()}' is currently unavailable."
        price = item["price"]
        if item_name in self.cart:
            self.cart[item_name]["qty"] += qty
        else:
            self.cart[item_name] = {"qty": qty, "price": price}
        self.cart[item_name]["line_total"] = self.cart[item_name]["qty"] * price
        return True, f"Added {qty} \u00d7 {item_name.title()} (\u20b9{price} each)."

    def remove_item(self, item_name):
        item_name = item_name.lower()
        if item_name in self.cart:
            del self.cart[item_name]
            return True, f"Removed '{item_name.title()}' from your order."
        return False, f"'{item_name.title()}' was not in your order."

    def update_item(self, item_name, qty):
        item_name = item_name.lower()
        if qty <= 0:
            return self.remove_item(item_name)
        menu = self.menu_dict
        if item_name not in menu:
            return False, f"'{item_name.title()}' is not on our menu."
        price = menu[item_name]["price"]
        self.cart[item_name] = {"qty": qty, "price": price, "line_total": qty * price}
        return True, f"Updated '{item_name.title()}' to {qty} \u00d7 \u20b9{price}."

    def clear_order(self):
        self.cart.clear()
        return True, "Your order has been cleared."

    def calculate_total(self):
        return sum(v["line_total"] for v in self.cart.values())

    def get_cart_summary(self):
        return [
            {"item_name": k.title(), "qty": v["qty"],
             "price": v["price"], "line_total": v["line_total"]}
            for k, v in self.cart.items()
        ]

    def is_empty(self):
        return len(self.cart) == 0

    def handle_items(self, intent, items, qty):
        messages = []
        if not items:
            messages.append("I couldn't find any menu items in your request. Please try again.")
            return messages
        for item_name in items:
            if intent == "REMOVE":
                _, msg = self.remove_item(item_name)
            elif intent == "UPDATE":
                _, msg = self.update_item(item_name, qty)
            else:
                _, msg = self.add_item(item_name, qty)
            messages.append(msg)
        return messages
