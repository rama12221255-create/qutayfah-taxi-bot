import tkinter as tk
from tkinter import messagebox

class DestinationSelectionApp:
    def __init__(self, root):
        self.root = root
        self.root.title("تحديد نقطة الوصول")
        self.root.geometry("400x520")
        self.root.config(bg="#f8f9fa")
        
        # متغير لتخزين الوجهة المختارة
        self.selected_destination = tk.StringVar(value="")
        
        self.create_widgets()

    def create_widgets(self):
        # عنوان الواجهة
        title_label = tk.Label(
            self.root, 
            text="اختر وجهة الوصول", 
            font=("Arial", 16, "bold"), 
            bg="#f8f9fa", 
            fg="#212529"
        )
        title_label.pack(pady=20)

        # زر تحديد الموقع عبر الخريطة (دبوس)
        pin_button = tk.Button(
            self.root, 
            text="📍 تحديد الموقع عبر الخريطة (دبوس)", 
            font=("Arial", 11, "bold"), 
            bg="#dc3545", 
            fg="white", 
            relief="flat",
            cursor="hand2",
            command=self.select_via_map
        )
        pin_button.pack(fill="x", padx=20, pady=10, ipady=10)

        # فاصل نصي
        or_label = tk.Label(
            self.root, 
            text="أو اختر من الأماكن المقترحة:", 
            font=("Arial", 11, "bold"), 
            bg="#f8f9fa", 
            fg="#495057"
        )
        or_label.pack(anchor="w", padx=20, pady=(15, 5))

        # قائمة الأماكن المقترحة
        destinations = [
            "مشفى القطيفة",
            "منتزه شباط",
            "منتزه المعضمية",
            "منتزه علوش"
        ]

        frame_destinations = tk.Frame(self.root, bg="#f8f9fa")
        frame_destinations.pack(fill="both", padx=20, pady=5)

        for dest in destinations:
            rb = tk.Radiobutton(
                frame_destinations, 
                text=dest, 
                variable=self.selected_destination, 
                value=dest,
                font=("Arial", 11),
                bg="#f8f9fa",
                fg="#212529",
                anchor="w",
                cursor="hand2"
            )
            rb.pack(fill="x", pady=6)

        # زر تأكيد الوجهة
        confirm_button = tk.Button(
            self.root, 
            text="تأكيد الوجهة", 
            font=("Arial", 12, "bold"), 
            bg="#28a745", 
            fg="white", 
            relief="flat",
            cursor="hand2",
            command=self.confirm_selection
        )
        confirm_button.pack(fill="x", padx=20, pady=25, ipady=10)

    def select_via_map(self):
        # محاكاة فتح الخريطة لتثبيت الدبوس
        self.selected_destination.set("تحديد دقيق عبر دبوس الخريطة")
        messagebox.showinfo("الخريطة", "تم تفعيل وضع تثبيت الدبوس على الخريطة بنجاح.")

    def confirm_selection(self):
        destination = self.selected_destination.get()
        if not destination:
            messagebox.showwarning("تنبيه", "الرجاء اختيار وجهة من القائمة أو تحديد الموقع عبر الخريطة أولاً!")
        else:
            messagebox.showinfo("تم بنجاح", f"تم اعتماد الوجهة التالية:\n{destination}")

if __name__ == "__main__":
    root = tk.Tk()
    app = DestinationSelectionApp(root)
    root.mainloop()
