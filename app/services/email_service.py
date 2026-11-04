"""Email service for sending OTP codes and transactional emails."""

import logging
import asyncio
from typing import Optional, List
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class EmailService:
    """Pluggable email service with responsive mobile/desktop templates and SMTP backend."""

    def __init__(self):
        self.mock_mode = getattr(settings, "MOC_EMAIL", False) or settings.EMAIL_BACKEND in ("console", "mock")
        self.mock_otp = getattr(settings, "MOC_OTP", False) or self.mock_mode

    # =========================================================================
    # MASTER RESPONSIVE EMAIL WRAPPER (MOBILE & DESKTOP OPTIMIZED)
    # =========================================================================
    def _wrap_email_template(
        self,
        title: str,
        subtitle: str = "",
        badge_text: str = "",
        content_html: str = "",
        accent_color: str = "#ea580c",
        footer_note: str = "",
        preheader: str = "",
    ) -> str:
        """
        Master responsive email wrapper compatible with Gmail, Apple Mail, Outlook,
        and all mobile & desktop email clients. Uses fluid nested tables.
        """
        preheader_html = f"""
        <!-- Hidden Preheader for email clients (Gmail, Apple Mail, Outlook) -->
        <div style="display:none; font-size:1px; color:#ffffff; line-height:1px; max-height:0px; max-width:0px; opacity:0; overflow:hidden; mso-hide:all;">
            {preheader}
        </div>
        """ if preheader else ""

        badge_html = f"""
        <div style="margin-bottom: 12px;">
            <span style="display: inline-block; background-color: #fff7ed; color: {accent_color}; font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; padding: 5px 14px; border-radius: 50px; border: 1px solid #fed7aa;">
                {badge_text}
            </span>
        </div>
        """ if badge_text else ""

        subtitle_html = f"""
        <p style="margin: 6px 0 0 0; font-size: 13px; font-weight: 600; color: #64748b; line-height: 1.4;">
            {subtitle}
        </p>
        """ if subtitle else ""

        footer_extra = f"""
        <p style="margin: 0 0 10px 0; font-size: 11px; color: #94a3b8; line-height: 1.4;">
            {footer_note}
        </p>
        """ if footer_note else ""

        return f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="en">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="format-detection" content="telephone=no, date=no, address=no, email=no" />
  <title>{title}</title>
  <style type="text/css">
    body, table, td, p, a, li, blockquote {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
    table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}
    img {{ -ms-interpolation-mode: bicubic; border: 0; outline: none; text-decoration: none; }}
    @media only screen and (max-width: 600px) {{
      .email-container {{ width: 100% !important; max-width: 100% !important; border-radius: 0 !important; }}
      .email-card-body {{ padding: 24px 18px !important; }}
      .email-header {{ padding: 24px 18px 12px 18px !important; }}
      .email-footer {{ padding: 20px 18px !important; }}
      .otp-digit {{ font-size: 30px !important; letter-spacing: 8px !important; }}
      .mobile-full-width {{ width: 100% !important; display: block !important; box-sizing: border-box !important; text-align: center !important; }}
      .mobile-stack {{ display: block !important; width: 100% !important; text-align: left !important; }}
      .mobile-center {{ text-align: center !important; }}
    }}
  </style>
</head>
<body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b; -webkit-font-smoothing: antialiased;">
  {preheader_html}
  <!-- Outer Table Wrapper -->
  <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f8fafc; padding: 24px 8px; margin: 0;">
    <tr>
      <td align="center" valign="top">
        <!-- Main Card Container -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" class="email-container" style="max-width: 560px; width: 100%; background-color: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 20px rgba(15, 23, 42, 0.05); margin: 0 auto;">
          <!-- Top Accent Brand Bar -->
          <tr>
            <td height="5" style="background-color: {accent_color}; line-height: 5px; font-size: 0;">&nbsp;</td>
          </tr>

          <!-- Header -->
          <tr>
            <td align="center" class="email-header" style="padding: 28px 28px 16px 28px; text-align: center;">
              {badge_html}
              <h1 style="margin: 0; font-size: 26px; font-weight: 800; letter-spacing: -0.5px; color: #0f172a;">
                <span style="color: #ea580c;">Menu</span><span style="color: #0f172a;">Kit</span>
              </h1>
              <h2 style="margin: 6px 0 0 0; font-size: 18px; font-weight: 700; color: #1e293b; line-height: 1.3;">
                {title}
              </h2>
              {subtitle_html}
            </td>
          </tr>

          <!-- Divider -->
          <tr>
            <td style="padding: 0 28px;">
              <hr style="border: 0; border-top: 1px solid #f1f5f9; margin: 0;" />
            </td>
          </tr>

          <!-- Card Content Body -->
          <tr>
            <td class="email-card-body" style="padding: 24px 28px 28px 28px; font-size: 14px; line-height: 1.6; color: #334155;">
              {content_html}
            </td>
          </tr>

          <!-- Divider -->
          <tr>
            <td style="padding: 0 28px;">
              <hr style="border: 0; border-top: 1px solid #f1f5f9; margin: 0;" />
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td align="center" class="email-footer" style="padding: 22px 28px; background-color: #fafafa; text-align: center; font-size: 11px; color: #94a3b8; line-height: 1.6;">
              {footer_extra}
              <p style="margin: 0 0 4px 0; font-weight: 700; color: #64748b;">
                <a href="https://debuggerstechnologies.com/" target="_blank" rel="noopener noreferrer" style="color: #475569; text-decoration: underline; font-weight: 700;">Debuggers Technologies</a> (<a href="https://debuggerstechnologies.com/menukit/" target="_blank" rel="noopener noreferrer" style="color: #ea580c; text-decoration: none; font-weight: 700;">MenuKit</a>)
              </p>
              <p style="margin: 0 0 4px 0; color: #94a3b8;">
                Perungudi, Madurai, Tamil Nadu - 625022, India
              </p>
              <p style="margin: 0; color: #94a3b8;">
                Support: <a href="mailto:debuggerstechs@gmail.com" style="color: #ea580c; text-decoration: none; font-weight: 600;">debuggerstechs@gmail.com</a> &bull; Mon&ndash;Sat 9:00 AM &ndash; 6:00 PM IST
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    # =========================================================================
    # 1. LOGIN OTP EMAIL
    # =========================================================================
    async def send_otp_email(self, email: str, otp_code: str, force_smtp: bool = False) -> bool:
        """Send OTP code to the given email address."""
        if not force_smtp and (self.mock_otp or settings.EMAIL_BACKEND in ("console", "mock")):
            return await self._send_console(email, otp_code)
        elif settings.EMAIL_BACKEND == "smtp" or force_smtp:
            return await self._send_smtp(email, otp_code)
        return await self._send_console(email, otp_code)

    async def _send_smtp(self, email: str, otp_code: str) -> bool:
        """Send Login OTP via Gmail SMTP with mobile/desktop structured template."""
        expire_mins = settings.OTP_EXPIRE_SECONDS // 60
        subject = f"Your MenuKit Verification Code is {otp_code}"
        
        text_content = f"""Your MenuKit Verification Code is: {otp_code}

Please enter the following verification code to sign in to your MenuKit account:
{otp_code}

This code expires in {expire_mins} minutes.

Never share this code with anyone. MenuKit staff will never ask for your verification code.

If you did not initiate this login attempt, you can safely ignore this email.
Debuggers Technologies - Perungudi, Madurai, Tamil Nadu - 625022, India
Support: debuggerstechs@gmail.com
"""
        body_html = f"""
        <div style="text-align: center; margin-bottom: 20px;">
            <p style="margin: 0 0 16px 0; font-size: 14px; color: #475569; line-height: 1.6;">
                Please enter the following verification code to sign in to your merchant dashboard:
            </p>
            
            <!-- OTP Box -->
            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 0 auto; background-color: #fff7ed; border: 2px dashed #ea580c; border-radius: 12px;">
                <tr>
                    <td style="padding: 20px 12px; text-align: center;">
                        <span class="otp-digit" style="font-family: 'SF Pro Mono', 'Cascadia Code', 'Consolas', monospace; font-size: 38px; font-weight: 800; letter-spacing: 8px; color: #ea580c; display: inline-block;">
                            {otp_code}
                        </span>
                    </td>
                </tr>
            </table>

            <div style="margin-top: 18px; padding: 12px 16px; background-color: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0; text-align: left;">
                <p style="margin: 0; font-size: 12px; color: #475569; line-height: 1.5;">
                    ⏱️ <strong>Valid for {expire_mins} minutes.</strong><br/>
                    🔒 Never share this OTP with anyone. MenuKit will never ask for your verification code.
                </p>
            </div>

            <p style="margin: 20px 0 0 0; font-size: 12px; color: #94a3b8; text-align: center;">
                If you did not initiate this login attempt, you can safely ignore this email.
            </p>
        </div>
        """
        html_content = self._wrap_email_template(
            title="Merchant Login Verification",
            subtitle="Access your store dashboard & live orders",
            badge_text="🔐 Secure Authentication",
            content_html=body_html,
            accent_color="#ea580c",
            footer_note="You received this email because a sign-in attempt was initiated for your MenuKit account.",
            preheader=f"Your MenuKit verification code is {otp_code}. Use this code to sign in.",
        )

        return await self._dispatch_raw_email(
            email=email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            sender_name="MenuKit"
        )

    # =========================================================================
    # 2. DELETION / DEACTIVATION SECURITY OTP EMAIL
    # =========================================================================
    async def send_deletion_otp_email(self, email: str, otp_code: str, target: str = "categories/items", force_smtp: bool = False) -> bool:
        """Send a specialized security OTP email for deleting/deactivating categories, shops, or master accounts."""
        clean_target = target.replace('_', ' ').strip()
        lower_target = clean_target.lower()
        if lower_target.startswith("category "):
            item_name = clean_target[9:].strip()
            target_display = f"Category '{item_name}'"
        elif lower_target in ("categories", "all categories"):
            target_display = "All Categories"
        elif lower_target in ("menu items", "menu_items"):
            target_display = "All Menu Items"
        elif lower_target.startswith("team member "):
            member_name = clean_target[12:].strip()
            target_display = f"Team Member ({member_name})"
        else:
            target_display = clean_target.title()

        subject = f"Your MenuKit Verification Code is {otp_code}"
        expire_mins = settings.OTP_EXPIRE_SECONDS // 60
        
        text_content = f"""Your MenuKit Verification Code is: {otp_code}

Please enter the following verification code to authorize the deactivation of {target_display}:
{otp_code}

This code expires in {expire_mins} minutes.

Restorable Soft-Deletion Architecture:
Your target records will be deactivated (is_deleted = True). All configurations and sales ledgers remain safely preserved in our database and can be restored at any time upon client request to debuggerstechs@gmail.com.

If you did not initiate this request, secure your account immediately.
Debuggers Technologies - Perungudi, Madurai, Tamil Nadu - 625022, India
Support: debuggerstechs@gmail.com
"""
        body_html = f"""
        <div style="text-align: center; margin-bottom: 20px;">
            <p style="margin: 0 0 16px 0; font-size: 14px; color: #475569; line-height: 1.6;">
                A request has been initiated to deactivate <strong>{target_display}</strong>.<br/>
                Please enter the following verification code to authorize this action:
            </p>
            
            <!-- OTP Box -->
            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 0 auto; background-color: #fff1f2; border: 2px dashed #f43f5e; border-radius: 12px;">
                <tr>
                    <td style="padding: 20px 12px; text-align: center;">
                        <span class="otp-digit" style="font-family: 'SF Pro Mono', 'Cascadia Code', 'Consolas', monospace; font-size: 38px; font-weight: 800; letter-spacing: 8px; color: #be123c; display: inline-block;">
                            {otp_code}
                        </span>
                    </td>
                </tr>
            </table>

            <div style="margin-top: 18px; padding: 14px 16px; background-color: #fef2f2; border-left: 4px solid #e11d48; border-radius: 8px; text-align: left;">
                <p style="margin: 0 0 6px 0; font-size: 12px; font-weight: 700; color: #9f1239;">
                    🛡️ Restorable Soft-Deletion Architecture:
                </p>
                <p style="margin: 0; font-size: 12px; color: #9f1239; line-height: 1.5;">
                    Your target records will be taken offline (<code>is_deleted = True</code>). All configurations, categories, menu items, and sales records remain safely preserved in our database and can be restored at any time by contacting support.
                </p>
            </div>

            <p style="margin: 20px 0 0 0; font-size: 12px; color: #94a3b8; text-align: center;">
                ⏱️ Valid for {expire_mins} minutes. If you did not make this request, secure your account immediately.
            </p>
        </div>
        """
        html_content = self._wrap_email_template(
            title="Security Verification Required",
            subtitle=f"Deactivation authorization for {target_display}",
            badge_text="⚠️ Security Alert",
            content_html=body_html,
            accent_color="#e11d48",
            footer_note="This sensitive security email is sent to verify destructive or deactivation actions on MenuKit.",
            preheader=f"Your MenuKit verification code is {otp_code}. Use this code to authorize the deactivation of {target_display}.",
        )

        if not force_smtp and (self.mock_mode or settings.EMAIL_BACKEND in ("console", "mock")):
            logger.info(f"🚨 [MOCK EMAIL] Deletion OTP for {email}: {otp_code}")
            return True

        return await self._dispatch_raw_email(
            email=email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            sender_name="MenuKit Security"
        )

    # =========================================================================
    # 3. TEAM / EMPLOYEE INVITATION EMAIL
    # =========================================================================
    async def send_employee_invite_email(self, email: str, token: str, shop_name: str, force_smtp: bool = False) -> bool:
        """Send an employee invitation email with verification link."""
        subject = f"You're invited to join {shop_name} on MenuKit"
        verify_url = f"{settings.FRONTEND_URL}/verify-employee?token={token}"
        
        logger.info(f"🔗 [EMPLOYEE VERIFICATION URL] Email: {email} | Shop: {shop_name} | URL: {verify_url}")
        
        text_content = f"""You're invited to join {shop_name} on MenuKit

You have been invited to join the staff team for {shop_name}.
Please open the link below to accept the invitation and activate your account:
{verify_url}

If you didn't expect this invitation, you can safely ignore this email.
Debuggers Technologies - Perungudi, Madurai, Tamil Nadu - 625022, India
Support: debuggerstechs@gmail.com
"""
        body_html = f"""
        <div style="text-align: center;">
            <p style="margin: 0 0 20px 0; font-size: 15px; line-height: 1.6; color: #334155;">
                You have been invited to join the team for <strong>{shop_name}</strong> on MenuKit.
            </p>
            <p style="margin: 0 0 26px 0; font-size: 13px; line-height: 1.5; color: #64748b;">
                Click the button below to accept your invitation, set up your credentials, and access your staff permissions:
            </p>

            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 0 auto 24px auto;">
                <tr>
                    <td align="center">
                        <a href="{verify_url}" class="mobile-full-width" style="display: inline-block; background-color: #ea580c; color: #ffffff; font-weight: 700; font-size: 15px; text-decoration: none; padding: 14px 36px; border-radius: 10px; box-shadow: 0 4px 12px rgba(234, 88, 12, 0.25);">
                            Verify and Accept Invitation &rarr;
                        </a>
                    </td>
                </tr>
            </table>

            <div style="background-color: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0; padding: 12px; font-size: 11px; color: #64748b; word-break: break-all; margin-top: 16px; text-align: left;">
                <strong>Direct Link:</strong><br/>
                <a href="{verify_url}" style="color: #ea580c; text-decoration: underline;">{verify_url}</a>
            </div>

            <p style="color: #94a3b8; font-size: 12px; text-align: center; margin: 20px 0 0 0;">
                If you did not anticipate this invitation, you can safely disregard this message.
            </p>
        </div>
        """
        html_content = self._wrap_email_template(
            title=f"Invitation to Join {shop_name}",
            subtitle="Staff Team & Operations Access",
            badge_text="👥 Team Invitation",
            content_html=body_html,
            accent_color="#ea580c",
            footer_note=f"Invitation issued by {shop_name} via MenuKit Team Management."
        )

        if not force_smtp and (self.mock_mode or settings.EMAIL_BACKEND in ("console", "mock")):
            return True

        return await self._dispatch_raw_email(
            email=email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            sender_name="MenuKit Team"
        )

    # =========================================================================
    # 4. SUBSCRIPTION INVOICE EMAIL
    # =========================================================================
    async def send_subscription_invoice_email(self, email: str, invoice_data: dict, force_smtp: bool = False) -> bool:
        """Send itemized subscription invoice via email."""
        from app.services.invoice_service import InvoiceService
        html_content = InvoiceService.render_invoice_html(invoice_data)
        subject = f"Invoice {invoice_data.get('invoice_number', '')} - MenuKit Subscription"
        
        text_content = f"""MenuKit Subscription Invoice

Invoice Number: {invoice_data.get('invoice_number', '')}
Total Amount: INR {invoice_data.get('total_amount', 0.0):.2f}
Payment Status: PAID

Thank you for your business!
Debuggers Technologies - Perungudi, Madurai, Tamil Nadu - 625022, India
Support: debuggerstechs@gmail.com
"""
        if not force_smtp and (self.mock_mode or settings.EMAIL_BACKEND in ("console", "mock")):
            logger.info(f"🧾 [MOCK EMAIL] Subscription Invoice {invoice_data.get('invoice_number')} sent to {email}")
            return True

        return await self._dispatch_raw_email(
            email=email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            sender_name="MenuKit Billing"
        )

    # =========================================================================
    # 5. SUBSCRIPTION EXPIRING SOON WARNING
    # =========================================================================
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
        subject = f"⚠️ Action Required: MenuKit Subscription Expiring in {min_days} Days"
        renew_url = f"{settings.FRONTEND_URL}/subscription/marketplace"
        
        text_content = f"""MenuKit Subscription Expiring Soon

Hi {shop_name},
Your access to {mods_str} will expire in {min_days} day(s).

Renew your modules to maintain uninterrupted online ordering, customer insights, and active features:
{renew_url}

Debuggers Technologies - Perungudi, Madurai, Tamil Nadu - 625022, India
Support: debuggerstechs@gmail.com
"""
        body_html = f"""
        <div>
            <p style="margin: 0 0 16px 0; font-size: 15px; color: #1e293b;">
                Hi <strong>{shop_name}</strong>,
            </p>
            <p style="margin: 0 0 20px 0; font-size: 14px; line-height: 1.6; color: #475569;">
                Your access to <strong style="color: #0f172a;">{mods_str}</strong> will expire in <span style="color: #ea580c; font-weight: 800;">{min_days} day(s)</span>.
            </p>

            <div style="background-color: #fff7ed; border-left: 4px solid #ea580c; padding: 16px; margin-bottom: 24px; border-radius: 8px; font-size: 13px; color: #9a3412; line-height: 1.5;">
                <strong>Keep your business running smoothly:</strong> Renew your active modules to avoid pauses in customer QR ordering, member analytics, or custom store branding.
            </div>

            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 0 auto 16px auto;">
                <tr>
                    <td align="center">
                        <a href="{renew_url}" class="mobile-full-width" style="display: inline-block; background-color: #ea580c; color: #ffffff; font-weight: 700; font-size: 15px; text-decoration: none; padding: 14px 36px; border-radius: 10px; box-shadow: 0 4px 12px rgba(234, 88, 12, 0.25);">
                            Renew Subscription Now &rarr;
                        </a>
                    </td>
                </tr>
            </table>
        </div>
        """
        html_content = self._wrap_email_template(
            title="Subscription Expiring Soon",
            subtitle=f"{shop_name} • Module Renewal Alert",
            badge_text=f"⏱️ {min_days} Days Remaining",
            content_html=body_html,
            accent_color="#ea580c",
            footer_note="Automated notification sent to maintain continuous service for your MenuKit store."
        )

        if not force_smtp and (self.mock_mode or settings.EMAIL_BACKEND in ("console", "mock")):
            return True

        return await self._dispatch_raw_email(
            email=email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            sender_name="MenuKit Subscriptions"
        )

    # =========================================================================
    # 6. SUBSCRIPTION EXPIRED ALERT
    # =========================================================================
    async def send_subscription_expired_email(self, email: str, shop_name: str, expired_modules: list = None, force_smtp: bool = False) -> bool:
        """Send notification email when subscription or modules have expired."""
        mods_str = ", ".join(expired_modules) if expired_modules else "subscription modules"
        subject = "Action Required: Your MenuKit Subscription Has Expired"
        renew_url = f"{settings.FRONTEND_URL}/subscription/marketplace"
        
        text_content = f"""MenuKit Subscription Expired

Hi {shop_name},
Your subscription for {mods_str} has expired. Some of your store's features have been paused.

Reactivate subscription:
{renew_url}

Debuggers Technologies - Perungudi, Madurai, Tamil Nadu - 625022, India
Support: debuggerstechs@gmail.com
"""
        body_html = f"""
        <div>
            <p style="margin: 0 0 16px 0; font-size: 15px; color: #1e293b;">
                Hi <strong>{shop_name}</strong>,
            </p>
            <p style="margin: 0 0 20px 0; font-size: 14px; line-height: 1.6; color: #475569;">
                Your subscription for <strong>{mods_str}</strong> has expired. Several premium tools have been paused.
            </p>

            <div style="background-color: #fef2f2; border-left: 4px solid #dc2626; padding: 16px; margin-bottom: 24px; border-radius: 8px; font-size: 13px; color: #991b1b; line-height: 1.5;">
                <strong>Restore Full Access:</strong> Subscribe now to instantly re-enable customer ordering, customized menus, and merchant insights.
            </div>

            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 0 auto 16px auto;">
                <tr>
                    <td align="center">
                        <a href="{renew_url}" class="mobile-full-width" style="display: inline-block; background-color: #dc2626; color: #ffffff; font-weight: 700; font-size: 15px; text-decoration: none; padding: 14px 36px; border-radius: 10px; box-shadow: 0 4px 12px rgba(220, 38, 38, 0.25);">
                            Reactivate Modules Now &rarr;
                        </a>
                    </td>
                </tr>
            </table>
        </div>
        """
        html_content = self._wrap_email_template(
            title="Subscription Expired",
            subtitle=f"{shop_name} • Store Features Paused",
            badge_text="🔴 Renewal Required",
            content_html=body_html,
            accent_color="#dc2626",
            footer_note="Your store data is safely preserved. Reactivate anytime to resume live features."
        )

        if not force_smtp and (self.mock_mode or settings.EMAIL_BACKEND in ("console", "mock")):
            return True

        return await self._dispatch_raw_email(
            email=email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            sender_name="MenuKit Subscriptions"
        )

    # =========================================================================
    # 7. NEW ORDER NOTIFICATION (POS & ADMIN)
    # =========================================================================
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
        items_summary_txt = []
        for it in items:
            name = getattr(it, "name", None) or (it.get("name") if isinstance(it, dict) else "Item")
            qty = getattr(it, "quantity", None) or (it.get("quantity") if isinstance(it, dict) else 1)
            price = float(getattr(it, "price", 0.0) or (it.get("price", 0.0) if isinstance(it, dict) else 0.0))
            subtotal = qty * price
            variant = getattr(it, "variant_info", None) or (it.get("variant_info") if isinstance(it, dict) else None)
            var_str = f"<br/><span style='font-size:11px; color:#ea580c; font-weight:600;'>({variant})</span>" if variant else ""
            items_summary_txt.append(f"- {name} x{qty} (₹{subtotal:.2f})")

            rows_html += f"""
            <tr style="border-bottom: 1px solid #f1f5f9;">
                <td style="padding: 10px 8px; font-size: 13px; color: #1e293b; font-weight: 600;">{name}{var_str}</td>
                <td style="padding: 10px 8px; font-size: 13px; color: #64748b; text-align: center; font-weight: 700;">x{qty}</td>
                <td style="padding: 10px 8px; font-size: 13px; color: #0f172a; text-align: right; font-weight: 800;">₹{subtotal:.2f}</td>
            </tr>
            """

        details_extra = ""
        location_line_txt = ""
        if delivery_address:
            details_extra = f"""
            <div style="margin-top: 8px; font-size: 12px; color: #475569; background: #ffffff; padding: 10px 12px; border-radius: 8px; border: 1px solid #e2e8f0;">
                <strong>📍 Delivery Address:</strong> {delivery_address}
            </div>
            """
            location_line_txt = f"Delivery Address: {delivery_address}"
        elif table_number:
            details_extra = f"""
            <div style="margin-top: 8px; font-size: 12px; color: #475569; background: #ffffff; padding: 10px 12px; border-radius: 8px; border: 1px solid #e2e8f0;">
                <strong>🪑 Table / Location:</strong> {table_number}
            </div>
            """
            location_line_txt = f"Table: {table_number}"

        text_content = f"""New Order Alert: {order_ref}
Shop: {shop_name}
Channel: {channel_label}
Customer: {customer_name} ({customer_phone})
Placed At: {created_at_str}
{location_line_txt}

Items:
{chr(10).join(items_summary_txt)}

Payment: {payment_method.replace('_', ' ').upper()} ({payment_status.upper()})
Grand Total: INR {total_amount:.2f}

View live orders: {settings.FRONTEND_URL}/orders
Debuggers Technologies - Perungudi, Madurai, Tamil Nadu - 625022, India
"""
        body_html = f"""
        <div>
            <!-- Overview Info Card -->
            <div style="background-color: #f8fafc; border-radius: 12px; padding: 16px; margin-bottom: 20px; font-size: 13px; border: 1px solid #e2e8f0;">
                <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
                    <tr>
                        <td style="padding: 4px 0; color: #64748b;">Order Reference:</td>
                        <td style="padding: 4px 0; text-align: right; font-weight: 800; color: #ea580c; font-size: 15px;">{order_ref}</td>
                    </tr>
                    <tr>
                        <td style="padding: 4px 0; color: #64748b;">Customer:</td>
                        <td style="padding: 4px 0; text-align: right; font-weight: 700; color: #0f172a;">{customer_name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 4px 0; color: #64748b;">Mobile:</td>
                        <td style="padding: 4px 0; text-align: right; font-weight: 700; color: #0f172a;"><a href="tel:{customer_phone}" style="color: #ea580c; text-decoration: none;">{customer_phone}</a></td>
                    </tr>
                    <tr>
                        <td style="padding: 4px 0; color: #64748b;">Channel:</td>
                        <td style="padding: 4px 0; text-align: right; font-weight: 700; color: #0284c7;">{channel_label}</td>
                    </tr>
                    <tr>
                        <td style="padding: 4px 0; color: #64748b;">Placed At:</td>
                        <td style="padding: 4px 0; text-align: right; color: #64748b;">{created_at_str}</td>
                    </tr>
                </table>
                {details_extra}
            </div>

            <!-- Items Table -->
            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom: 20px; border-collapse: collapse;">
                <thead>
                    <tr style="border-bottom: 2px solid #e2e8f0; text-align: left;">
                        <th style="padding: 8px; font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: 800;">Item</th>
                        <th style="padding: 8px; font-size: 11px; text-transform: uppercase; color: #64748b; text-align: center; font-weight: 800;">Qty</th>
                        <th style="padding: 8px; font-size: 11px; text-transform: uppercase; color: #64748b; text-align: right; font-weight: 800;">Amount</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>

            <!-- Grand Total Highlight -->
            <div style="background-color: #fff7ed; border-radius: 12px; padding: 16px; margin-bottom: 24px; border: 1px solid #ffedd5;">
                <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
                    <tr>
                        <td style="font-size: 12px; color: #9a3412;">
                            Payment: <strong>{payment_method.replace('_', ' ').upper()}</strong> ({payment_status.upper()})
                        </td>
                    </tr>
                    <tr>
                        <td style="padding-top: 10px; border-top: 1px solid #fed7aa;">
                            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
                                <tr>
                                    <td style="font-size: 15px; font-weight: 800; color: #431407;">Grand Total:</td>
                                    <td style="font-size: 24px; font-weight: 900; color: #ea580c; text-align: right;">₹{total_amount:.2f}</td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                </table>
            </div>

            <!-- Action Button -->
            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
                <tr>
                    <td align="center">
                        <a href="{settings.FRONTEND_URL}/orders" class="mobile-full-width" style="display: inline-block; background-color: #ea580c; color: #ffffff; font-weight: 700; font-size: 14px; text-decoration: none; padding: 14px 32px; border-radius: 10px; box-shadow: 0 4px 12px rgba(234, 88, 12, 0.25);">
                            Open in POS / Live Orders &rarr;
                        </a>
                    </td>
                </tr>
            </table>
        </div>
        """
        html_content = self._wrap_email_template(
            title=f"New Order: {order_ref}",
            subtitle=f"{shop_name} • Live Dispatch Alert",
            badge_text=f"🛒 {channel_label}",
            content_html=body_html,
            accent_color="#ea580c",
            footer_note="Live order notification delivered automatically to the merchant dispatch team."
        )

        if not force_smtp and (self.mock_mode or settings.EMAIL_BACKEND in ("console", "mock")):
            return True

        return await self._dispatch_raw_email(
            email=email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            sender_name="MenuKit Orders"
        )

    # =========================================================================
    # 8. SCHEME ENROLLMENT NOTIFICATION
    # =========================================================================
    async def send_scheme_enrollment_email(
        self,
        email: str,
        shop_name: str,
        scheme_title: str,
        member_number: str,
        customer_name: str,
        customer_phone: str,
        customer_address: str | None,
        installment_amount: float,
        term_duration: int,
        frequency: str,
        term_unit: str,
        payment_method: str,
        joined_at_str: str,
        force_smtp: bool = False,
    ) -> bool:
        """Send immediate email notification to merchant when a customer enrolls in a savings scheme."""
        freq_label = frequency.capitalize() if frequency else "Monthly"
        duration_label = f"{term_duration} {term_unit.title() if term_unit else 'Months'}"
        pay_method_label = "Razorpay (Online)" if "razorpay" in str(payment_method).lower() else str(payment_method).title()

        subject = f"🪙 New Scheme Member Enrolled: {customer_name} ({member_number}) — {scheme_title} | {shop_name}"

        address_row = f"""
        <tr style="border-bottom: 1px solid #f1f5f9;">
            <td style="padding: 10px 8px; font-size: 13px; color: #64748b; font-weight: 600;">Address</td>
            <td style="padding: 10px 8px; font-size: 13px; color: #1e293b; font-weight: 600; text-align: right;">{customer_address.strip()}</td>
        </tr>
        """ if customer_address and customer_address.strip() else ""

        text_content = f"""New Scheme Member Enrolled
Customer: {customer_name} ({customer_phone})
Scheme: {scheme_title}
Pass Number: {member_number}
Installment: INR {installment_amount:.2f} / {freq_label}
Duration: {duration_label}
Initial Payment: Paid ({pay_method_label})

View Schemes: {settings.FRONTEND_URL}/schemes
Debuggers Technologies - Perungudi, Madurai, Tamil Nadu - 625022, India
"""
        body_html = f"""
        <div>
            <!-- Scheme Banner -->
            <div style="background-color: #fffbeb; border: 1px solid #fde68a; border-radius: 12px; padding: 18px; margin-bottom: 20px; text-align: center;">
                <span style="font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; color: #92400e;">Savings Scheme</span>
                <h3 style="font-size: 18px; font-weight: 800; color: #78350f; margin: 4px 0 8px 0;">{scheme_title}</h3>
                <span style="display: inline-block; background-color: #ffffff; border-radius: 20px; padding: 4px 14px; font-size: 13px; font-weight: 800; color: #b45309; border: 1px solid #fde68a;">
                    Pass: {member_number}
                </span>
            </div>

            <!-- Enrollment Details Table -->
            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse; margin-bottom: 24px;">
                <tr style="border-bottom: 1px solid #f1f5f9;">
                    <td style="padding: 10px 8px; font-size: 13px; color: #64748b; font-weight: 600;">Customer</td>
                    <td style="padding: 10px 8px; font-size: 13px; color: #0f172a; font-weight: 700; text-align: right;">{customer_name}</td>
                </tr>
                <tr style="border-bottom: 1px solid #f1f5f9;">
                    <td style="padding: 10px 8px; font-size: 13px; color: #64748b; font-weight: 600;">Mobile</td>
                    <td style="padding: 10px 8px; font-size: 13px; color: #0f172a; font-weight: 700; text-align: right;"><a href="tel:{customer_phone}" style="color: #ea580c; text-decoration: none;">{customer_phone}</a></td>
                </tr>
                {address_row}
                <tr style="border-bottom: 1px solid #f1f5f9;">
                    <td style="padding: 10px 8px; font-size: 13px; color: #64748b; font-weight: 600;">Installment</td>
                    <td style="padding: 10px 8px; font-size: 14px; color: #16a34a; font-weight: 800; text-align: right;">₹{installment_amount:,.2f} / {freq_label}</td>
                </tr>
                <tr style="border-bottom: 1px solid #f1f5f9;">
                    <td style="padding: 10px 8px; font-size: 13px; color: #64748b; font-weight: 600;">Term Duration</td>
                    <td style="padding: 10px 8px; font-size: 13px; color: #1e293b; font-weight: 700; text-align: right;">{duration_label}</td>
                </tr>
                <tr style="border-bottom: 1px solid #f1f5f9;">
                    <td style="padding: 10px 8px; font-size: 13px; color: #64748b; font-weight: 600;">Initial Payment</td>
                    <td style="padding: 10px 8px; font-size: 13px; color: #16a34a; font-weight: 700; text-align: right;">Paid ({pay_method_label})</td>
                </tr>
            </table>

            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
                <tr>
                    <td align="center">
                        <a href="{settings.FRONTEND_URL}/schemes" class="mobile-full-width" style="display: inline-block; background-color: #d97706; color: #ffffff; padding: 13px 30px; text-decoration: none; border-radius: 10px; font-weight: 700; font-size: 14px; box-shadow: 0 4px 12px rgba(217, 119, 6, 0.25);">
                            View Schemes & Members &rarr;
                        </a>
                    </td>
                </tr>
            </table>
        </div>
        """
        html_content = self._wrap_email_template(
            title=f"{customer_name} Enrolled!",
            subtitle=f"{shop_name} • Savings & Loyalty Pass",
            badge_text="🪙 New Scheme Member",
            content_html=body_html,
            accent_color="#d97706",
            footer_note="Automated notification delivered via MenuKit Savings Scheme Manager."
        )

        if not force_smtp and (self.mock_mode or settings.EMAIL_BACKEND in ("console", "mock")):
            return True

        return await self._dispatch_raw_email(
            email=email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            sender_name="MenuKit Schemes"
        )

    # =========================================================================
    # 9. WEEKEND / WEEKLY SUMMARY DIGEST
    # =========================================================================
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

        text_content = f"""Weekend Digest: {shop_name}
{weekend_label} • Performance Summary

Total Customers: {total_customers:,}
New Customers This Week: {new_customers_this_week:,}
Orders Completed: {orders_this_week:,}
Gross Revenue: INR {revenue_this_week:,.2f}

View full metrics: {settings.FRONTEND_URL}/analytics
Debuggers Technologies - Perungudi, Madurai, Tamil Nadu - 625022, India
"""
        body_html = f"""
        <div>
            <!-- Highlight Total Customers Banner -->
            <div style="background-color: #ea580c; border-radius: 14px; padding: 22px; text-align: center; color: #ffffff; margin-bottom: 22px; box-shadow: 0 4px 16px rgba(234, 88, 12, 0.25);">
                <span style="font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; opacity: 0.9;">Total Registered Customers</span>
                <div style="font-size: 40px; font-weight: 900; margin: 4px 0 2px 0;">{total_customers:,}</div>
                <span style="font-size: 12px; opacity: 0.9;">Across In-Store & Online Channels</span>
            </div>

            <!-- Stats Grid -->
            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom: 24px;">
                <tr>
                    <td width="33%" style="padding: 12px; background-color: #f8fafc; border-radius: 10px; border: 1px solid #e2e8f0; text-align: center;">
                        <span style="font-size: 10px; text-transform: uppercase; font-weight: 800; color: #64748b;">New</span>
                        <div style="font-size: 20px; font-weight: 900; color: #0f172a; margin-top: 4px;">+{new_customers_this_week:,}</div>
                    </td>
                    <td width="4%" style="font-size: 0;">&nbsp;</td>
                    <td width="30%" style="padding: 12px; background-color: #f8fafc; border-radius: 10px; border: 1px solid #e2e8f0; text-align: center;">
                        <span style="font-size: 10px; text-transform: uppercase; font-weight: 800; color: #64748b;">Orders</span>
                        <div style="font-size: 20px; font-weight: 900; color: #0f172a; margin-top: 4px;">{orders_this_week:,}</div>
                    </td>
                    <td width="4%" style="font-size: 0;">&nbsp;</td>
                    <td width="33%" style="padding: 12px; background-color: #f8fafc; border-radius: 10px; border: 1px solid #e2e8f0; text-align: center;">
                        <span style="font-size: 10px; text-transform: uppercase; font-weight: 800; color: #64748b;">Revenue</span>
                        <div style="font-size: 18px; font-weight: 900; color: #16a34a; margin-top: 4px;">₹{revenue_this_week:,.0f}</div>
                    </td>
                </tr>
            </table>

            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
                <tr>
                    <td align="center">
                        <a href="{settings.FRONTEND_URL}/analytics" class="mobile-full-width" style="display: inline-block; background-color: #ea580c; color: #ffffff; padding: 13px 32px; text-decoration: none; border-radius: 10px; font-weight: 700; font-size: 14px; box-shadow: 0 4px 12px rgba(234, 88, 12, 0.25);">
                            Open Store Analytics &rarr;
                        </a>
                    </td>
                </tr>
            </table>
        </div>
        """
        html_content = self._wrap_email_template(
            title="Weekly Store Performance Digest",
            subtitle=f"{shop_name} • {weekend_label}",
            badge_text="📊 Performance Digest",
            content_html=body_html,
            accent_color="#ea580c",
            footer_note="Delivered automatically to store owners as part of your MenuKit analytics suite."
        )

        if not force_smtp and (self.mock_mode or settings.EMAIL_BACKEND in ("console", "mock")):
            return True

        return await self._dispatch_raw_email(
            email=email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            sender_name="MenuKit Analytics"
        )

    # =========================================================================
    # 10. CONTACT / DEMO ENQUIRY EMAIL
    # =========================================================================
    async def send_contact_enquiry_email(
        self,
        name: str,
        email: str,
        phone: str,
        country: str,
        district: str,
        state: str = "",
        business_name: str = "",
        enquiry_type: str = "Demo Request",
        message: str = "",
        target_email: str = "debuggerstechs@gmail.com",
        force_smtp: bool = False,
    ) -> bool:
        """Send notification of a customer enquiry / demo request to the business owner."""
        subject = f"🚀 New MenuKit Enquiry ({enquiry_type}): {name} - {district}, {country}"

        location_str = f"{district}, {state}, {country}" if state else f"{district}, {country}"
        business_row = f"""
        <tr style="border-bottom: 1px solid #f1f5f9;">
            <td style="padding: 10px 8px; font-weight: 600; color: #475569; width: 140px;">Business / Store:</td>
            <td style="padding: 10px 8px; color: #0f172a; font-weight: 700; text-align: right;">{business_name}</td>
        </tr>
        """ if business_name else ""

        message_box = f"""
        <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px; margin-top: 16px;">
            <span style="font-size: 11px; font-weight: 800; text-transform: uppercase; color: #64748b; letter-spacing: 0.5px;">Customer Message:</span>
            <p style="margin: 6px 0 0 0; color: #1e293b; font-size: 13px; line-height: 1.5; white-space: pre-wrap;">{message}</p>
        </div>
        """ if message else ""

        text_content = f"""New MenuKit Enquiry: {enquiry_type}
Contact: {name}
Email: {email}
Phone: {phone}
Location: {location_str}
Business: {business_name or 'Not specified'}

Message:
{message or 'None'}

Debuggers Technologies - Perungudi, Madurai, Tamil Nadu - 625022, India
"""
        body_html = f"""
        <div>
            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse; margin-bottom: 16px;">
                <tr style="border-bottom: 1px solid #f1f5f9;">
                    <td style="padding: 10px 8px; font-weight: 600; color: #475569; width: 140px;">Contact Name:</td>
                    <td style="padding: 10px 8px; color: #0f172a; font-weight: 700; text-align: right;">{name}</td>
                </tr>
                <tr style="border-bottom: 1px solid #f1f5f9;">
                    <td style="padding: 10px 8px; font-weight: 600; color: #475569;">Mobile:</td>
                    <td style="padding: 10px 8px; color: #ea580c; font-weight: 800; text-align: right;">
                        <a href="tel:{phone}" style="color: #ea580c; text-decoration: none;">{phone}</a>
                    </td>
                </tr>
                <tr style="border-bottom: 1px solid #f1f5f9;">
                    <td style="padding: 10px 8px; font-weight: 600; color: #475569;">Email:</td>
                    <td style="padding: 10px 8px; color: #0f172a; font-weight: 600; text-align: right;">
                        <a href="mailto:{email}" style="color: #0284c7; text-decoration: none;">{email}</a>
                    </td>
                </tr>
                <tr style="border-bottom: 1px solid #f1f5f9;">
                    <td style="padding: 10px 8px; font-weight: 600; color: #475569;">Location:</td>
                    <td style="padding: 10px 8px; color: #0f172a; font-weight: 600; text-align: right;">{location_str}</td>
                </tr>
                {business_row}
            </table>

            {message_box}

            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 22px;">
                <tr>
                    <td align="center">
                        <a href="tel:{phone}" class="mobile-full-width" style="display: inline-block; background-color: #ea580c; color: #ffffff; padding: 13px 30px; text-decoration: none; border-radius: 10px; font-weight: 700; font-size: 14px; box-shadow: 0 4px 12px rgba(234, 88, 12, 0.25);">
                            📞 Call Customer Back &rarr;
                        </a>
                    </td>
                </tr>
            </table>
        </div>
        """
        html_content = self._wrap_email_template(
            title=f"New Enquiry: {enquiry_type}",
            subtitle=f"Lead from {district}, {country}",
            badge_text="✨ New Inbound Lead",
            content_html=body_html,
            accent_color="#ea580c",
            footer_note="Submitted via MenuKit Public Contact & Support Portal."
        )

        if not force_smtp and (self.mock_mode or settings.EMAIL_BACKEND in ("console", "mock")):
            return True

        return await self._dispatch_raw_email(
            email=target_email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            sender_name="MenuKit Leads"
        )

    # =========================================================================
    # CORE DISPATCH ENGINE (GMAIL SMTP WITH AUTOMATIC RETRIES & DUAL MIME)
    # =========================================================================
    async def _send_console(self, email: str, otp_code: str) -> bool:
        """Log mock OTP to console (development/mock mode)."""
        logger.info(f"[MOCK OTP] Email to {email}: {otp_code}")
        print(f"\n============================================================")
        print(f">>> [MOCK OTP ACTIVE - NO REAL EMAIL SENT] <<<")
        print(f"* Email Recipient : {email}")
        print(f"* Email OTP Code  : {otp_code}")
        print(f"* Valid for       : {settings.OTP_EXPIRE_SECONDS // 60} minutes")
        print(f"============================================================\n")
        return True

    async def _dispatch_raw_email(
        self,
        email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
        sender_name: str = "MenuKit"
    ) -> bool:
        """Helper to send arbitrary HTML & plain-text emails via SMTP with retry mechanism."""
        import aiosmtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from email.utils import formataddr

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = formataddr((sender_name, settings.SMTP_FROM_EMAIL))
        msg["To"] = email
        msg["Reply-To"] = settings.SMTP_FROM_EMAIL

        # Attach text/plain first for clean preview snippets in Gmail notifications
        if text_content:
            msg.attach(MIMEText(text_content, "plain", "utf-8"))
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        use_tls = settings.SMTP_PORT == 465
        start_tls = settings.SMTP_PORT == 587

        last_error = None
        for attempt in range(1, 4):
            try:
                await aiosmtplib.send(
                    msg,
                    hostname=settings.SMTP_HOST,
                    port=settings.SMTP_PORT,
                    username=settings.SMTP_USER,
                    password=settings.SMTP_PASSWORD,
                    use_tls=use_tls,
                    start_tls=start_tls,
                    timeout=20,
                )
                logger.info(f"Successfully dispatched email to {email} (attempt {attempt})")
                return True
            except Exception as e:
                last_error = e
                logger.warning(f"SMTP dispatch attempt {attempt}/3 failed for {email}: {e}")
                if attempt < 3:
                    await asyncio.sleep(2)

        logger.error(f"Failed to dispatch email to {email} after 3 attempts: {last_error}")
        print(f"\n==================================================")
        print(f"FAILED TO DISPATCH GMAIL SMTP EMAIL to {email}: {last_error}")
        print(f"==================================================\n")
        return False


email_service = EmailService()
