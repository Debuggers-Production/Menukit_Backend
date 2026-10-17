"""Email service for sending OTP codes."""

import logging
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class EmailService:
    """Pluggable email service. Console/Mock and SMTP backends."""

    def __init__(self):
        self.mock_mode = getattr(settings, "MOC_EMAIL", False) or settings.EMAIL_BACKEND in ("console", "mock")
        self.mock_otp = getattr(settings, "MOC_OTP", False) or self.mock_mode

    async def send_otp_email(self, email: str, otp_code: str, force_smtp: bool = False) -> bool:
        """Send OTP code to the given email address."""
        if not force_smtp and (self.mock_otp or settings.EMAIL_BACKEND in ("console", "mock")):
            return await self._send_console(email, otp_code)
        elif settings.EMAIL_BACKEND == "smtp" or force_smtp:
            return await self._send_smtp(email, otp_code)
        # Default fallback to mock console
        return await self._send_console(email, otp_code)

    async def send_deletion_otp_email(self, email: str, otp_code: str, target: str = "categories/items", force_smtp: bool = False) -> bool:
        """Send a specialized security OTP email for deleting categories/items."""
        subject = f"⚠️ Security Alert: OTP to Confirm Deletion of {target.title()} ({otp_code})"
        
        html_content = f"""
        <html>
        <body style="font-family: 'Inter', system-ui, -apple-system, sans-serif; padding: 40px; background: #f8fafc; color: #1e293b;">
            <div style="max-width: 480px; margin: 0 auto; background: #ffffff; border-radius: 16px; padding: 36px; box-shadow: 0 4px 24px rgba(0,0,0,0.08); border: 1px solid #e2e8f0;">
                <div style="text-align: center; margin-bottom: 24px;">
                    <div style="display: inline-block; background: #fef2f2; border-radius: 50%; padding: 16px; margin-bottom: 12px;">
                        <span style="font-size: 32px;">⚠️</span>
                    </div>
                    <h2 style="color: #dc2626; font-size: 22px; font-weight: 700; margin: 0;">Deletion Verification Required</h2>
                    <p style="color: #64748b; font-size: 14px; margin-top: 6px;">Action requested: Bulk Delete {target.title()}</p>
                </div>

                <div style="background: #fef2f2; border: 2px dashed #fca5a5; border-radius: 12px; padding: 24px; text-align: center; margin-bottom: 24px;">
                    <p style="color: #991b1b; font-size: 13px; font-weight: 600; margin-top: 0; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 1px;">Your Deletion Verification Code</p>
                    <span style="font-size: 38px; font-weight: 800; letter-spacing: 10px; color: #dc2626; font-family: monospace;">{otp_code}</span>
                </div>

                <div style="background: #fff7ed; border-left: 4px solid #f97316; border-radius: 8px; padding: 14px 16px; margin-bottom: 24px; font-size: 13px; color: #9a3412; line-height: 1.5;">
                    <strong>Warning:</strong> Deleting categories or menu items will permanently erase all associated data. If you did not initiate this deletion request, please secure your account immediately.
                </div>

                <p style="color: #94a3b8; font-size: 13px; text-align: center; margin: 0;">This code is valid for {settings.OTP_EXPIRE_SECONDS // 60} minutes. Do not share this OTP with anyone.</p>
            </div>
        </body>
        </html>
        """

        if not force_smtp and (self.mock_mode or settings.EMAIL_BACKEND in ("console", "mock")):
            logger.info(f"🚨 [MOCK EMAIL] Deletion OTP for {email}: {otp_code}")
            print(f"\n\033[91m{'=' * 55}\033[0m")
            print(f"\033[91m🚨 DELETION OTP EMAIL to: \033[1m{email}\033[0m")
            print(f"\033[93m🔑 OTP Code: \033[1m{otp_code}\033[0m | Target: \033[1m{target}\033[0m")
            print(f"\033[91m{'=' * 55}\n\033[0m")
            return True

        return await self._dispatch_raw_email(email, subject, html_content)

    async def send_employee_invite_email(self, email: str, token: str, shop_name: str, force_smtp: bool = False) -> bool:
        """Send an employee invitation email with verification link."""
        subject = f"You're invited to join {shop_name} on SmartMenu"
        verify_url = f"{settings.FRONTEND_URL}/verify-employee?token={token}"
        
        # Always log employee verification URL via logger for easy development & audit tracking
        logger.info(f"🔗 [EMPLOYEE VERIFICATION URL] Email: {email} | Shop: {shop_name} | URL: {verify_url}")
        
        html_content = f"""
        <html>
        <body style="font-family: 'Inter', system-ui, -apple-system, sans-serif; padding: 40px; background: #f8fafc; color: #1e293b;">
            <div style="max-width: 480px; margin: 0 auto; background: #ffffff; border-radius: 16px; padding: 36px; box-shadow: 0 4px 24px rgba(0,0,0,0.08); border: 1px solid #e2e8f0;">
                <h2 style="color: #0f172a; font-size: 22px; font-weight: 700; margin: 0 0 16px 0;">Invitation to join {shop_name}</h2>
                <p style="color: #475569; font-size: 15px; line-height: 1.6; margin-bottom: 24px;">
                    You have been invited to join the team for <strong>{shop_name}</strong>. Please click the button below to accept the invitation and verify your email address.
                </p>
                <div style="text-align: center; margin-bottom: 24px;">
                    <a href="{verify_url}" style="display: inline-block; background-color: #4f46e5; color: #ffffff; font-weight: 600; text-decoration: none; padding: 12px 24px; border-radius: 8px;">Verify and Accept Invitation</a>
                </div>
                <p style="color: #94a3b8; font-size: 13px; text-align: center; margin: 0;">If you didn't expect this, you can safely ignore this email.</p>
            </div>
        </body>
        </html>
        """

        if not force_smtp and (self.mock_mode or settings.EMAIL_BACKEND in ("console", "mock")):
            print(f"\n\033[94m{'=' * 55}\033[0m")
            print(f"\033[94m💌 EMPLOYEE INVITE EMAIL to: \033[1m{email}\033[0m")
            print(f"\033[96m🔗 Verify URL: \033[1m{verify_url}\033[0m")
            print(f"\033[94m{'=' * 55}\n\033[0m")
            return True

        return await self._dispatch_raw_email(email, subject, html_content)

    async def _send_console(self, email: str, otp_code: str) -> bool:
        """Log mock OTP to console (development/mock mode)."""
        GREEN = "\033[92m"
        CYAN = "\033[96m"
        YELLOW = "\033[93m"
        RESET = "\033[0m"
        BOLD = "\033[1m"
        
        logger.info(f"[MOCK OTP] Email to {email}: {otp_code}")
        print(f"\n{CYAN}{'=' * 60}{RESET}")
        print(f"{YELLOW}>>> [MOCK OTP ACTIVE - NO REAL EMAIL SENT] <<<{RESET}")
        print(f"{CYAN}* Email Recipient : {BOLD}{email}{RESET}")
        print(f"{GREEN}* Email OTP Code  : {BOLD}{otp_code}{RESET}")
        print(f"{CYAN}* Valid for       : {settings.OTP_EXPIRE_SECONDS // 60} minutes{RESET}")
        print(f"{CYAN}{'=' * 60}\n{RESET}")
        return True

    async def _send_smtp(self, email: str, otp_code: str) -> bool:
        """Send OTP via SMTP (production mode)."""
        try:
            import aiosmtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"Your SmartMenu QR Login Code: {otp_code}"
            msg["From"] = settings.SMTP_FROM_EMAIL
            msg["To"] = email

            html_content = f"""
            <html>
            <body style="font-family: 'Inter', sans-serif; padding: 40px; background: #f8fafc;">
                <div style="max-width: 400px; margin: 0 auto; background: white; border-radius: 16px; padding: 40px; box-shadow: 0 4px 24px rgba(0,0,0,0.08);">
                    <h1 style="color: #f97316; font-size: 24px; margin-bottom: 8px;">SmartMenu QR</h1>
                    <p style="color: #64748b; margin-bottom: 24px;">Your login verification code</p>
                    <div style="background: #fff7ed; border: 2px solid #f97316; border-radius: 12px; padding: 24px; text-align: center; margin-bottom: 24px;">
                        <span style="font-size: 36px; font-weight: 700; letter-spacing: 8px; color: #ea580c;">{otp_code}</span>
                    </div>
                    <p style="color: #94a3b8; font-size: 14px;">This code expires in {settings.OTP_EXPIRE_SECONDS // 60} minutes. Do not share it with anyone.</p>
                </div>
            </body>
            </html>
            """

            msg.attach(MIMEText(html_content, "html"))

            use_tls = settings.SMTP_PORT == 465
            start_tls = settings.SMTP_PORT == 587

            await aiosmtplib.send(
                msg,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USER,
                password=settings.SMTP_PASSWORD,
                use_tls=use_tls,
                start_tls=start_tls,
            )
            return True
        except Exception as e:
            # ANSI escape codes for colored terminal output
            RED = "\033[91m"
            YELLOW = "\033[93m"
            RESET = "\033[0m"
            BOLD = "\033[1m"
            
            logger.error(f"{RED}{BOLD}❌ Failed to send email: {e}{RESET}")
            print(f"\n{RED}{'=' * 50}{RESET}")
            print(f"{RED}{BOLD}❌ EMAIL SEND ERROR: {e}{RESET}")
            print(f"{YELLOW}💡 Fallback Development OTP Code for {email}: {BOLD}{otp_code}{RESET}")
            print(f"{RED}{'=' * 50}\n{RESET}")
            return False

    async def send_subscription_invoice_email(self, email: str, invoice_data: dict, force_smtp: bool = False) -> bool:
        """Send itemized subscription invoice via email."""
        from app.services.invoice_service import InvoiceService
        html_content = InvoiceService.render_invoice_html(invoice_data)
        subject = f"Invoice {invoice_data['invoice_number']} - SmartMenu QR Subscription"
        
        if not force_smtp and (self.mock_mode or settings.EMAIL_BACKEND in ("console", "mock")):
            logger.info(f"🧾 [MOCK EMAIL] Subscription Invoice {invoice_data['invoice_number']} sent to {email}")
            print(f"\n\033[96m{'=' * 60}\033[0m")
            print(f"\033[96m🧾 [MOCK EMAIL] INVOICE SENT TO: \033[1m{email}\033[0m")
            print(f"\033[92mInv #: {invoice_data['invoice_number']} | Amount: ₹{invoice_data['total_amount']:.2f}\033[0m")
            print(f"\033[96m{'=' * 60}\n\033[0m")
            return True

        return await self._dispatch_raw_email(email, subject, html_content)

    async def send_subscription_expiring_email(
        self,
        email: str,
        shop_name: str,
        min_days: int = 3,
        expiring_modules: list = None,
        force_smtp: bool = False
    ) -> bool:
        """Send warning email when subscription or modules are expiring soon."""
        mods_str = ", ".join(expiring_modules) if expiring_modules else "subscription modules"
        subject = f"⚠️ Action Required: SmartMenu Subscription Expiring in {min_days} Days"
        
        html_content = f"""
        <html>
        <body style="font-family: 'Inter', sans-serif; padding: 32px; background: #f8fafc; color: #334155;">
            <div style="max-width: 500px; margin: 0 auto; background: white; border-radius: 16px; padding: 32px; box-shadow: 0 4px 20px rgba(0,0,0,0.06); border: 1px solid #e2e8f0;">
                <h2 style="color: #ea580c; font-size: 20px; margin-bottom: 8px;">Subscription Expiring Soon</h2>
                <p style="color: #64748b; font-size: 14px;">Hi {shop_name},</p>
                <p style="font-size: 14px; line-height: 1.6;">Your access to <strong>{mods_str}</strong> will expire in <span style="color: #dc2626; font-weight: 800;">{min_days} day(s)</span>.</p>
                <div style="background: #fff7ed; border-left: 4px solid #ea580c; padding: 16px; margin: 20px 0; border-radius: 8px; font-size: 13px;">
                    Renew your modules to maintain uninterrupted online ordering, customer insights, and active features!
                </div>
                <p style="text-align: center; margin-top: 24px;">
                    <a href="{settings.FRONTEND_URL}/subscription/marketplace" style="background: #f97316; color: white; padding: 12px 24px; text-decoration: none; border-radius: 10px; font-weight: 700; display: inline-block;">Renew Subscription Now</a>
                </p>
            </div>
        </body>
        </html>
        """

        if not force_smtp and (self.mock_mode or settings.EMAIL_BACKEND in ("console", "mock")):
            logger.info(f"[MOCK EMAIL] Expiring Warning ({min_days} days left) sent to {email}")
            print(f"\n\033[93m[WARN] [MOCK EMAIL] EXPIRING SOON ALERT to {email} ({min_days} days left for {mods_str})\033[0m\n")
            return True

        return await self._dispatch_raw_email(email, subject, html_content)

    async def send_subscription_expired_email(self, email: str, shop_name: str, expired_modules: list = None, force_smtp: bool = False) -> bool:
        """Send notification email when subscription or modules have expired."""
        mods_str = ", ".join(expired_modules) if expired_modules else "subscription modules"
        subject = "Action Required: Your SmartMenu Subscription Has Expired"
        
        html_content = f"""
        <html>
        <body style="font-family: 'Inter', sans-serif; padding: 32px; background: #f8fafc; color: #334155;">
            <div style="max-width: 500px; margin: 0 auto; background: white; border-radius: 16px; padding: 32px; box-shadow: 0 4px 20px rgba(0,0,0,0.06); border: 1px solid #e2e8f0;">
                <h2 style="color: #dc2626; font-size: 20px; margin-bottom: 8px;">Subscription Expired</h2>
                <p style="color: #64748b; font-size: 14px;">Hi {shop_name},</p>
                <p style="font-size: 14px; line-height: 1.6;">Your subscription for <strong>{mods_str}</strong> has expired. Some of your store's premium features have been paused.</p>
                <div style="background: #fef2f2; border-left: 4px solid #dc2626; padding: 16px; margin: 20px 0; border-radius: 8px; font-size: 13px; color: #991b1b;">
                    Subscribe now to instantly restore full access to your digital ordering, member analytics, and custom theme tools.
                </div>
                <p style="text-align: center; margin-top: 24px;">
                    <a href="{settings.FRONTEND_URL}/subscription/marketplace" style="background: #dc2626; color: white; padding: 12px 24px; text-decoration: none; border-radius: 10px; font-weight: 700; display: inline-block;">Reactivate Subscription</a>
                </p>
            </div>
        </body>
        </html>
        """

        if not force_smtp and (self.mock_mode or settings.EMAIL_BACKEND in ("console", "mock")):
            logger.info(f"[MOCK EMAIL] Expired Notification sent to {email}")
            print(f"\n\033[91m[EXPIRED] [MOCK EMAIL] EXPIRED ALERT to {email} ({mods_str})\033[0m\n")
            return True

        return await self._dispatch_raw_email(email, subject, html_content)

    async def send_new_order_admin_email(
        self,
        email: str,
        shop_name: str,
        order_ref: str,
        customer_name: str,
        customer_phone: str,
        order_type: str,
        table_number: str | None,
        delivery_address: str | None,
        payment_method: str,
        payment_status: str,
        total_amount: float,
        items: list,
        created_at_str: str,
        force_smtp: bool = False,
    ) -> bool:
        """Send immediate email notification to admin when a new order is placed."""
        channel_label = order_type.replace("_", " ").title()
        if order_type == "dine_in" and table_number:
            channel_label = f"Dine-in ({table_number})"
        elif order_type == "delivery":
            channel_label = "Delivery"

        subject = f"🛒 New Order {order_ref} ({channel_label}) - ₹{total_amount:.2f} | {shop_name}"

        rows_html = ""
        for it in items:
            name = getattr(it, "name", None) or (it.get("name") if isinstance(it, dict) else "Item")
            qty = getattr(it, "quantity", None) or (it.get("quantity") if isinstance(it, dict) else 1)
            price = float(getattr(it, "price", 0.0) or (it.get("price", 0.0) if isinstance(it, dict) else 0.0))
            subtotal = qty * price
            variant = getattr(it, "variant_info", None) or (it.get("variant_info") if isinstance(it, dict) else None)
            var_str = f"<br/><span style='font-size:11px; color:#ea580c; font-weight:600;'>({variant})</span>" if variant else ""

            rows_html += f"""
            <tr style="border-bottom: 1px solid #f1f5f9;">
                <td style="padding: 10px 8px; font-size: 13px; color: #1e293b; font-weight: 600;">{name}{var_str}</td>
                <td style="padding: 10px 8px; font-size: 13px; color: #64748b; text-align: center; font-weight: 700;">x{qty}</td>
                <td style="padding: 10px 8px; font-size: 13px; color: #0f172a; text-align: right; font-weight: 800;">₹{subtotal:.2f}</td>
            </tr>
            """

        details_extra = ""
        if delivery_address:
            details_extra += f"""
            <div style="margin-top: 8px; font-size: 12px; color: #64748b; background: #ffffff; padding: 8px 12px; border-radius: 6px; border: 1px solid #e2e8f0;">
                <strong>📍 Delivery Address:</strong> {delivery_address}
            </div>
            """
        elif table_number:
            details_extra += f"""
            <div style="margin-top: 8px; font-size: 12px; color: #64748b; background: #ffffff; padding: 8px 12px; border-radius: 6px; border: 1px solid #e2e8f0;">
                <strong>🪑 Table / Location:</strong> {table_number}
            </div>
            """

        html_content = f"""
        <html>
        <body style="font-family: 'Inter', system-ui, -apple-system, sans-serif; padding: 32px; background: #f8fafc; color: #1e293b; margin: 0;">
            <div style="max-width: 520px; margin: 0 auto; background: #ffffff; border-radius: 16px; padding: 32px; box-shadow: 0 4px 24px rgba(0,0,0,0.06); border: 1px solid #e2e8f0;">
                <div style="border-bottom: 2px solid #ea580c; padding-bottom: 16px; margin-bottom: 20px;">
                    <span style="font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; color: #ea580c;">SmartMenu QR • New Order Alert</span>
                    <h2 style="color: #0f172a; font-size: 22px; font-weight: 800; margin: 4px 0 0 0;">{shop_name}</h2>
                </div>

                <div style="background: #f8fafc; border-radius: 12px; padding: 14px 16px; margin-bottom: 20px; font-size: 13px; border: 1px solid #e2e8f0;">
                    <div style="margin-bottom: 6px;">
                        <span style="color: #64748b;">Order Reference:</span>
                        <strong style="color: #ea580c; font-size: 14px;"> {order_ref}</strong>
                    </div>
                    <div style="margin-bottom: 6px;">
                        <span style="color: #64748b;">Customer:</span>
                        <strong style="color: #0f172a;"> {customer_name}</strong>
                    </div>
                    <div style="margin-bottom: 6px;">
                        <span style="color: #64748b;">Phone:</span>
                        <strong style="color: #0f172a;"> {customer_phone}</strong>
                    </div>
                    <div style="margin-bottom: 6px;">
                        <span style="color: #64748b;">Channel:</span>
                        <span style="font-weight: 700; color: #0284c7;"> {channel_label}</span>
                    </div>
                    <div>
                        <span style="color: #64748b;">Placed At:</span>
                        <span style="color: #64748b;"> {created_at_str}</span>
                    </div>
                    {details_extra}
                </div>

                <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
                    <thead>
                        <tr style="border-bottom: 2px solid #e2e8f0; text-align: left;">
                            <th style="padding: 8px; font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: 700;">Item</th>
                            <th style="padding: 8px; font-size: 11px; text-transform: uppercase; color: #64748b; text-align: center; font-weight: 700;">Qty</th>
                            <th style="padding: 8px; font-size: 11px; text-transform: uppercase; color: #64748b; text-align: right; font-weight: 700;">Amount</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>

                <div style="background: #fff7ed; border-radius: 12px; padding: 16px; margin-bottom: 24px; border: 1px solid #ffedd5;">
                    <div style="font-size: 13px; color: #9a3412; margin-bottom: 6px;">
                        Payment: <strong>{payment_method.replace('_', ' ').upper()}</strong> ({payment_status.upper()})
                    </div>
                    <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #fed7aa; padding-top: 8px;">
                        <span style="font-size: 15px; font-weight: 800; color: #431407;">Grand Total:</span>
                        <span style="font-size: 22px; font-weight: 900; color: #ea580c;">₹{total_amount:.2f}</span>
                    </div>
                </div>

                <div style="text-align: center;">
                    <a href="{settings.FRONTEND_URL}/orders" style="display: inline-block; background-color: #ea580c; color: #ffffff; font-weight: 700; font-size: 14px; text-decoration: none; padding: 12px 28px; border-radius: 10px;">
                        View Live Order in POS
                    </a>
                </div>
            </div>
        </body>
        </html>
        """

        if not force_smtp and (self.mock_mode or settings.EMAIL_BACKEND in ("console", "mock")):
            logger.info(f"[MOCK EMAIL] New Order {order_ref} notification to {email}")
            print(f"\n\033[92m{'=' * 60}\033[0m")
            print(f"\033[92m[ORDER] NEW ORDER EMAIL NOTIFICATION to: \033[1m{email}\033[0m")
            print(f"\033[93mOrder {order_ref} | {customer_name} ({channel_label}) | Total: INR {total_amount:.2f}\033[0m")
            print(f"\033[92m{'=' * 60}\n\033[0m")
            return True

        return await self._dispatch_raw_email(email, subject, html_content)

    async def send_weekend_customer_summary_email(
        self,
        email: str,
        shop_name: str,
        total_customers: int,
        new_customers_this_week: int,
        orders_this_week: int,
        revenue_this_week: float,
        weekend_label: str = "Weekly Customer Digest",
        force_smtp: bool = False,
    ) -> bool:
        """Send weekend summary email with total customer count and weekly activity."""
        subject = f"Weekend Digest: {total_customers} Total Customers for {shop_name}"

        html_content = f"""
        <html>
        <body style="font-family: 'Inter', system-ui, -apple-system, sans-serif; padding: 32px; background: #f8fafc; color: #1e293b; margin: 0;">
            <div style="max-width: 520px; margin: 0 auto; background: #ffffff; border-radius: 16px; padding: 36px; box-shadow: 0 4px 24px rgba(0,0,0,0.06); border: 1px solid #e2e8f0;">
                <div style="text-align: center; margin-bottom: 24px;">
                    <span style="font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 1.5px; color: #ea580c;">SmartMenu QR • Weekend Digest</span>
                    <h2 style="color: #0f172a; font-size: 24px; font-weight: 900; margin: 6px 0 2px 0;">{shop_name}</h2>
                    <p style="color: #64748b; font-size: 13px; margin: 0;">{weekend_label} • Customer & Performance Report</p>
                </div>

                <!-- Total Customers Highlight Card -->
                <div style="background: linear-gradient(135deg, #ea580c, #f97316); border-radius: 14px; padding: 24px; text-align: center; color: white; margin-bottom: 20px; box-shadow: 0 8px 20px rgba(234, 88, 12, 0.25);">
                    <span style="font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; opacity: 0.9;">Total Registered Customers</span>
                    <div style="font-size: 44px; font-weight: 900; line-height: 1.1; margin: 8px 0 4px 0;">{total_customers:,}</div>
                    <span style="font-size: 12px; opacity: 0.95;">Active customer members in your shop database</span>
                </div>

                <!-- 3 Stats Grid -->
                <table style="width: 100%; border-collapse: separate; border-spacing: 8px; margin-bottom: 20px;">
                    <tr>
                        <td style="width: 50%; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 14px; text-align: center;">
                            <span style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: #64748b;">New This Week</span>
                            <div style="font-size: 22px; font-weight: 800; color: #16a34a; margin-top: 4px;">+{new_customers_this_week:,}</div>
                        </td>
                        <td style="width: 50%; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 14px; text-align: center;">
                            <span style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: #64748b;">Orders This Week</span>
                            <div style="font-size: 22px; font-weight: 800; color: #2563eb; margin-top: 4px;">{orders_this_week:,}</div>
                        </td>
                    </tr>
                </table>

                <div style="background: #f1f5f9; border-radius: 12px; padding: 16px 20px; margin-bottom: 24px; border: 1px solid #e2e8f0;">
                    <span style="font-size: 13px; font-weight: 700; color: #334155;">Weekly Total Revenue: </span>
                    <strong style="font-size: 18px; font-weight: 800; color: #0f172a;">INR {revenue_this_week:,.2f}</strong>
                </div>

                <div style="text-align: center;">
                    <a href="{settings.FRONTEND_URL}/crm" style="display: inline-block; background-color: #0f172a; color: #ffffff; font-weight: 700; font-size: 13px; text-decoration: none; padding: 12px 28px; border-radius: 10px;">
                        Open Customer CRM
                    </a>
                </div>
            </div>
        </body>
        </html>
        """

        if not force_smtp and (self.mock_mode or settings.EMAIL_BACKEND in ("console", "mock")):
            logger.info(f"[MOCK EMAIL] Weekend customer summary sent to {email}: {total_customers} customers")
            print(f"\n\033[95m{'=' * 60}\033[0m")
            print(f"\033[95m[DIGEST] WEEKEND CUSTOMER SUMMARY EMAIL to: \033[1m{email}\033[0m")
            print(f"\033[93mTotal Customers: {total_customers} (+{new_customers_this_week} this week) | Revenue: INR {revenue_this_week:.2f}\033[0m")
            print(f"\033[95m{'=' * 60}\n\033[0m")
            return True

        return await self._dispatch_raw_email(email, subject, html_content)

    async def _dispatch_raw_email(self, email: str, subject: str, html_content: str) -> bool:
        """Helper to send arbitrary HTML emails via SMTP."""
        try:
            import aiosmtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = settings.SMTP_FROM_EMAIL
            msg["To"] = email

            msg.attach(MIMEText(html_content, "html"))

            use_tls = settings.SMTP_PORT == 465
            start_tls = settings.SMTP_PORT == 587

            await aiosmtplib.send(
                msg,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USER,
                password=settings.SMTP_PASSWORD,
                use_tls=use_tls,
                start_tls=start_tls,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to dispatch email to {email}: {e}")
            return False

email_service = EmailService()
