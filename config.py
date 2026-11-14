"""
Configuration constants for ScrapeDatAqar pipeline.
Supports dynamic environment variable overrides for Docker containerization.
"""

import os

BASE_CITY_URL = os.getenv('BASE_CITY_URL', 'https://sa.aqar.fm/%D8%B9%D9%82%D8%A7%D8%B1%D8%A7%D8%AA/%D8%A7%D9%84%D8%B1%D9%8A%D8%A7%D8%B6')
FLARESOLVERR_URL = os.getenv('FLARESOLVERR_URL', 'http://127.0.0.1:8191/v1')

DATA_DIR = os.getenv('DATA_DIR', './data')
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, 'aqar_riyadh_city.db')
CSV_PATH = os.path.join(DATA_DIR, 'aqar_riyadh_city_53cols.csv')
EXCEL_PATH = os.path.join(DATA_DIR, 'aqar_riyadh_city_53cols.xlsx')

PORT = int(os.getenv('PORT', '8099'))
MAX_WORKERS = int(os.getenv('MAX_WORKERS', '4'))
REQUEST_TIMEOUT = 14
FLARE_TIMEOUT = 45000

CSV_HEADERS = [
    "رقم الإعلان", "تصنيف البحث في الرياض", "القسم / الفئة", "عنوان العقار", "السعر (ريال)",
    "دورية الدفع", "السعر الإجمالي الموثق (هيئة العقار)", "المساحة (م²)", "مساحة الصك (م²)",
    "المدينة / المحافظة", "الحي", "العنوان التفصيلي", "رقم ترخيص الإعلان", "رقم الصك",
    "رقم المخطط", "رقم القطعة", "المخطط والقطعة", "موثق من الهيئة", "اسم المعلن / الوسيط",
    "رقم رخصة فال", "صفة المعلن", "رقم هاتف المعلن", "غرف النوم", "الصالات", "دورات المياه",
    "الدور", "عمر العقار", "نوع العقار", "عرض الشارع", "الواجهة", "مكيفات راكبة", "مؤثثة",
    "مدخل سيارة", "مدخلين", "مدخل خاص", "في فيلا", "شبكة المياه", "شبكة الكهرباء",
    "شبكة الصرف الصحي", "خط العرض (Lat)", "خط الطول (Lng)", "المشاهدات", "الإعجابات",
    "المفضلة", "تاريخ الإضافة", "تاريخ التحديث",
    "رابط صفحة البحث / القائمة (الصفحة التي ظهر فيها الإعلان)",
    "رابط الإعلان المباشر", "رابط الإعلان المختصر",
    "وصف العقار", "عدد الصور", "روابط الصور", "فيديو الإعلان"
]
