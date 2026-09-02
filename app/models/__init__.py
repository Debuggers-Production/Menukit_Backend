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
from app.models.contest import Contest, ContestParticipation, ContestCredit, ContestLike, ContestComment, ContestCommentLike
from app.models.order import Order, OrderItem
from app.models.oauth import OAuthClient, OAuthAuthorizationCode, OAuthRefreshToken
from app.models.employee import Employee
from app.models.menu_catalog import MenuCatalog
from app.models.branch_item_override import BranchItemOverride
from app.models.broadcast import BroadcastCampaign

__all__ = [
    "BroadcastCampaign",
    "User",

    "Employee",
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
    "Contest",
    "ContestParticipation",
    "ContestCredit",
    "ContestLike",
    "ContestComment",
    "ContestCommentLike",
    "Order",
    "OrderItem",
    "OAuthClient",
    "OAuthAuthorizationCode",
    "OAuthRefreshToken",
    "MenuCatalog",
    "BranchItemOverride",
]
