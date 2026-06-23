"""Models package - imports all models for SQLAlchemy registration."""

from app.models.user import User
from app.models.otp import OTPCode
from app.models.session import Session
from app.models.shop import Shop
from app.models.shop_settings import ShopSettings
from app.models.theme_settings import ThemeSettings
from app.models.category import Category
from app.models.menu_item import MenuItem
from app.models.menu_image import MenuImage
from app.models.qr_code import QRCode
from app.models.analytics import QRScan, MenuView, SearchHistory, MembershipEvent
from app.models.activity_log import ActivityLog
from app.models.discount import Discount
from app.models.review import MenuItemReview
from app.models.customer import Customer
from app.models.membership import CustomerRetailerMembership
from app.models.notification import Notification
from app.models.subscription import Subscription, PaymentTransaction

__all__ = [
    "User",
    "OTPCode",
    "Session",
    "Shop",
    "ShopSettings",
    "ThemeSettings",
    "Category",
    "MenuItem",
    "MenuImage",
    "QRCode",
    "QRScan",
    "MenuView",
    "SearchHistory",
    "ActivityLog",
    "Discount",
    "MenuItemReview",
    "Customer",
    "CustomerRetailerMembership",
    "MembershipEvent",
    "Notification",
    "Subscription",
    "PaymentTransaction",
]
