"""Contest service."""

import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.contest import Contest, ContestParticipation, ContestCredit, ContestLike, ContestComment, ContestCommentLike
from app.models.customer import Customer
from app.models.shop import Shop
from app.core.exceptions import NotFoundException
from app.services.whatsapp_service import WhatsAppClient


class ContestService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _notify_all_registered_customers_new_contest(self, shop_name: str, contest_title: str, reward_value: str, shop_id: uuid.UUID):
        """Send WhatsApp message to all registered customers about a new contest."""
        try:
            res = await self.db.execute(select(Customer.mobile_number))
            mobiles = res.scalars().all()
            if not mobiles:
                return

            wa = WhatsAppClient()
            msg = (
                f"🎨 *NEW CONTEST ALERT at {shop_name}!* 🏆\n\n"
                f"Contest: *{contest_title}*\n"
                f"Reward: *{reward_value}*\n\n"
                f"Show your creativity and win exciting rewards! Join now:\n"
                f"https://menukit.debuggers.co.in/shop/{shop_id}/contest"
            )

            for phone in mobiles:
                try:
                    wa.send_text_message(phone_number=phone, message=msg)
                except Exception as e:
                    print(f"Failed to send contest WhatsApp to {phone}: {e}")
        except Exception as err:
            print(f"Error broadcasting new contest WhatsApp: {err}")

    async def _notify_contest_winner(self, customer_id: uuid.UUID, contest_title: str, reward_value: str, shop_name: str):
        """Send WhatsApp intimation message to the contest winner."""
        try:
            res = await self.db.execute(select(Customer).where(Customer.id == customer_id))
            customer = res.scalar_one_or_none()
            if not customer or not customer.mobile_number:
                return

            wa = WhatsAppClient()
            msg = (
                f"🎉 *CONGRATULATIONS {customer.name or 'Winner'}!* 🏆\n\n"
                f"You have WON the contest *{contest_title}* at *{shop_name}*!\n"
                f"Your Prize: *{reward_value}* 🎁\n\n"
                f"Thank you for participating! Visit the store to claim your reward."
            )
            wa.send_text_message(phone_number=customer.mobile_number, message=msg)
        except Exception as err:
            print(f"Error sending winner WhatsApp intimation: {err}")

    async def _notify_contest_cancelled(self, contest_id: uuid.UUID, contest_title: str, shop_name: str, cancel_reason: str):
        """Send WhatsApp intimation message to participants when a contest is cancelled."""
        try:
            part_result = await self.db.execute(
                select(ContestParticipation)
                .where(ContestParticipation.contest_id == contest_id)
                .options(selectinload(ContestParticipation.customer))
            )
            participations = list(part_result.scalars().all())
            if not participations:
                return

            wa = WhatsAppClient()
            msg = (
                f"ℹ️ *CONTEST CANCELLED NOTICE* - *{shop_name}*\n\n"
                f"Contest: *{contest_title}*\n"
                f"Reason: *{cancel_reason}*\n\n"
                f"🔄 *Credit Refund*: 1 Contest Credit has been automatically refunded back to your account balance!\n"
                f"Thank you for participating. Check out active contests anytime!"
            )

            notified_phones = set()
            for p in participations:
                if p.customer and p.customer.mobile_number and p.customer.mobile_number not in notified_phones:
                    notified_phones.add(p.customer.mobile_number)
                    try:
                        wa.send_text_message(phone_number=p.customer.mobile_number, message=msg)
                    except Exception as e:
                        print(f"Failed to send cancellation WhatsApp to {p.customer.mobile_number}: {e}")
        except Exception as err:
            print(f"Error sending contest cancellation WhatsApp: {err}")

    async def _get_user_shop(self, user_id: uuid.UUID) -> Shop:
        result = await self.db.execute(select(Shop).where(Shop.user_id == user_id))
        shop = result.scalar_one_or_none()
        if not shop:
            raise NotFoundException("Shop not found. Create a shop first.")
        return shop

    async def create_contest(self, user_id: uuid.UUID, data: dict) -> Contest:
        shop = await self._get_user_shop(user_id)
        
        # Check if there is already an active ongoing contest for this shop
        existing_active_res = await self.db.execute(
            select(Contest).where(Contest.shop_id == shop.id, Contest.status == "active")
        )
        for ec in existing_active_res.scalars().all():
            ec = await self._evaluate_contest_status(ec)
            if ec.status == "active":
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=400,
                    detail="You already have an active contest running. Please wait for it to complete or cancel it before creating a new one."
                )

        # End date is 3 days from now
        ends_at = datetime.now(timezone.utc) + timedelta(days=3)

        contest = Contest(
            shop_id=shop.id,
            status="active",
            ends_at=ends_at,
            **data
        )
        self.db.add(contest)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(contest)

        # Broadcast WhatsApp notification asynchronously to all registered customers
        asyncio.create_task(
            self._notify_all_registered_customers_new_contest(
                shop_name=shop.name or "Merchant",
                contest_title=contest.title,
                reward_value=contest.reward_value or "Special Reward",
                shop_id=shop.id
            )
        )

        return contest

    async def refund_contest_credits(self, contest_id: uuid.UUID):
        part_result = await self.db.execute(
            select(ContestParticipation).where(
                ContestParticipation.contest_id == contest_id,
                ContestParticipation.is_submitted == True
            )
        )
        participations = list(part_result.scalars().all())
        for p in participations:
            credit_result = await self.db.execute(
                select(ContestCredit).where(ContestCredit.customer_id == p.customer_id)
            )
            credit = credit_result.scalar_one_or_none()
            if credit:
                credit.credits = round(float(credit.credits) + 1.0, 2)
            else:
                self.db.add(ContestCredit(customer_id=p.customer_id, credits=1.0))
        await self.db.commit()

    async def _evaluate_contest_status(self, contest: Contest) -> Contest:
        now = datetime.now(timezone.utc)
        if contest.status == "active" and contest.ends_at < now:
            part_result = await self.db.execute(
                select(ContestParticipation).where(ContestParticipation.contest_id == contest.id)
            )
            participations = list(part_result.scalars().all())
            part_count = len(participations)
            max_likes = max([getattr(p, "likes_count", 0) for p in participations], default=0)
            max_comments = max([getattr(p, "comments_count", 0) for p in participations], default=0)
            max_shares = max([getattr(p, "shares_count", 0) for p in participations], default=0)

            min_parts = getattr(contest, "min_participants", 1) or 1
            min_lk = getattr(contest, "min_likes", 1) or 1
            min_cm = getattr(contest, "min_comments", 0) or 0
            min_sh = getattr(contest, "min_shares", 0) or 0
            criterion = getattr(contest, "ranking_criterion", "likes") or "likes"

            targets_met = part_count >= min_parts

            if criterion == "likes" or criterion == "all":
                targets_met = targets_met and (max_likes >= min_lk)
            if criterion == "comments" or criterion == "all":
                targets_met = targets_met and (max_comments >= min_cm)
            if criterion == "shares" or criterion == "all":
                targets_met = targets_met and (max_shares >= min_sh)

            if targets_met:
                contest.status = "completed"
                # Flag top ranked participation as winner
                if participations:
                    sorted_parts = sorted(
                        participations,
                        key=lambda p: (
                            getattr(p, "likes_count", 0) or 0,
                            getattr(p, "comments_count", 0) or 0,
                            getattr(p, "time_remaining_seconds", 0) or 0
                        ),
                        reverse=True
                    )
                    winner_part = sorted_parts[0]
                    winner_part.is_winner = True
                    
                    # Notify winner via WhatsApp
                    asyncio.create_task(
                        self._notify_contest_winner(winner_part.customer_id, contest.title, contest.reward_value, shop.name if 'shop' in locals() else "Shop")
                    )

                # Award 0.15 participation bonus credits to non-winning participants
                for p in participations:
                    credit_res = await self.db.execute(
                        select(ContestCredit).where(ContestCredit.customer_id == p.customer_id)
                    )
                    credit_obj = credit_res.scalar_one_or_none()
                    if not credit_obj:
                        credit_obj = ContestCredit(customer_id=p.customer_id, credits=0.15)
                        self.db.add(credit_obj)
                    else:
                        credit_obj.credits = round(float(credit_obj.credits) + 0.15, 2)
            else:
                contest.status = "cancelled"
                contest.cancel_reason = "Minimum targets not reached (Credits refunded)"
                await self.refund_contest_credits(contest.id)
                
                # Notify participants via WhatsApp that contest was cancelled and credits were refunded
                asyncio.create_task(
                    self._notify_contest_cancelled(
                        contest_id=contest.id,
                        contest_title=contest.title,
                        shop_name="Merchant Store",
                        cancel_reason=contest.cancel_reason
                    )
                )
            
            await self.db.commit()
            await self.db.refresh(contest)
        return contest

    async def cancel_contest_by_merchant(self, contest_id: uuid.UUID, reason: str = "Cancelled by merchant") -> Contest:
        result = await self.db.execute(
            select(Contest)
            .where(Contest.id == contest_id)
            .options(selectinload(Contest.shop))
        )
        contest = result.scalar_one_or_none()
        if not contest:
            raise NotFoundException("Contest not found.")

        contest.status = "cancelled"
        contest.cancel_reason = reason
        await self.refund_contest_credits(contest.id)

        # Send WhatsApp intimation to all participants that contest was cancelled and credits refunded
        asyncio.create_task(
            self._notify_contest_cancelled(
                contest_id=contest.id,
                contest_title=contest.title,
                shop_name=contest.shop.name if contest.shop else "Merchant Store",
                cancel_reason=reason
            )
        )

        await self.db.commit()
        await self.db.refresh(contest)
        return contest

    async def get_contests_by_shop(self, shop_id: uuid.UUID) -> List[Contest]:
        from sqlalchemy.orm import selectinload
        result = await self.db.execute(
            select(Contest)
            .options(selectinload(Contest.participations))
            .where(Contest.shop_id == shop_id)
            .order_by(Contest.created_at.desc())
        )
        contests = list(result.scalars().all())
        updated_contests = []
        for c in contests:
            updated_c = await self._evaluate_contest_status(c)
            updated_contests.append(updated_c)
        return updated_contests

    async def get_active_contest(self, shop_id: uuid.UUID) -> Optional[Contest]:
        result = await self.db.execute(
            select(Contest)
            .where(Contest.shop_id == shop_id, Contest.status == "active")
        )
        contest = result.scalar_one_or_none()
        if contest:
            contest = await self._evaluate_contest_status(contest)
            if contest.status != "active":
                return None
        return contest

    async def get_credits(self, customer_id: uuid.UUID) -> float:
        result = await self.db.execute(
            select(ContestCredit).where(ContestCredit.customer_id == customer_id)
        )
        credit = result.scalar_one_or_none()
        if not credit:
            credit = ContestCredit(customer_id=customer_id, credits=0.0)
            self.db.add(credit)
            await self.db.commit()
            await self.db.refresh(credit)
        return round(float(credit.credits), 2)

    async def add_credits(self, mobile_number: str) -> ContestCredit:
        result = await self.db.execute(
            select(Customer).where(Customer.mobile_number == mobile_number)
        )
        customer = result.scalar_one_or_none()
        if not customer:
            raise NotFoundException("Customer not found. Verify mobile first.")

        credit_result = await self.db.execute(
            select(ContestCredit).where(ContestCredit.customer_id == customer.id)
        )
        credit = credit_result.scalar_one_or_none()
        if not credit:
            credit = ContestCredit(customer_id=customer.id, credits=1.0)
            self.db.add(credit)
        else:
            credit.credits = round(float(credit.credits) + 1.0, 2)

        await self.db.commit()
        await self.db.refresh(credit)
        return credit

    async def participate_contest(self, contest_id: uuid.UUID, customer_id: uuid.UUID, content_type: str) -> ContestParticipation:
        # 1. Check contest is active
        contest_result = await self.db.execute(select(Contest).where(Contest.id == contest_id))
        contest = contest_result.scalar_one_or_none()
        if not contest:
            raise NotFoundException("Contest not found.")
        if contest.status != "active" or contest.ends_at < datetime.now(timezone.utc):
            raise ValueError("This contest has ended or is inactive.")

        # 2. Verify customer has enough credits (Needs 1 credit to enter/start timer)
        credit_result = await self.db.execute(
            select(ContestCredit).where(ContestCredit.customer_id == customer_id)
        )
        credit = credit_result.scalar_one_or_none()
        if not credit or credit.credits < 1.0:
            raise ValueError("Insufficient credits (1 Credit required). Please pay ₹5 or make orders >= ₹100 to earn 0.15 credits!")

        # 3. Create participation (Credits will ONLY be deducted upon final submission)
        participation = ContestParticipation(
            contest_id=contest_id,
            customer_id=customer_id,
            content_type=content_type,
            time_remaining_seconds=600,
            is_timer_running=False,
            is_submitted=False
        )
        self.db.add(participation)
        await self.db.commit()
        await self.db.refresh(participation)
        return participation

    async def toggle_timer(self, participation_id: uuid.UUID, customer_id: uuid.UUID, start_timer: bool) -> ContestParticipation:
        result = await self.db.execute(
            select(ContestParticipation).where(
                ContestParticipation.id == participation_id,
                ContestParticipation.customer_id == customer_id
            )
        )
        participation = result.scalar_one_or_none()
        if not participation:
            raise NotFoundException("Participation record not found.")

        if participation.is_submitted:
            raise ValueError("Contest already submitted.")

        now = datetime.now(timezone.utc)

        if start_timer:
            if not participation.is_timer_running:
                # Start or resume
                participation.is_timer_running = True
                participation.timer_last_updated_at = now
        else:
            if participation.is_timer_running:
                # Pause
                elapsed = (now - participation.timer_last_updated_at).total_seconds()
                participation.time_remaining_seconds = max(0, int(participation.time_remaining_seconds - elapsed))
                participation.is_timer_running = False
                participation.timer_last_updated_at = None

        await self.db.commit()
        await self.db.refresh(participation)
        return participation

    async def submit_participation(self, participation_id: uuid.UUID, customer_id: uuid.UUID, text_content: Optional[str] = None, media_url: Optional[str] = None) -> ContestParticipation:
        result = await self.db.execute(
            select(ContestParticipation).where(
                ContestParticipation.id == participation_id,
                ContestParticipation.customer_id == customer_id
            )
        )
        participation = result.scalar_one_or_none()
        if not participation:
            raise NotFoundException("Participation record not found.")

        if participation.is_submitted:
            raise ValueError("Already submitted.")

        now = datetime.now(timezone.utc)

        # Update remaining time if timer was running
        if participation.is_timer_running and participation.timer_last_updated_at:
            elapsed = (now - participation.timer_last_updated_at).total_seconds()
            participation.time_remaining_seconds = max(0, int(participation.time_remaining_seconds - elapsed))
            participation.is_timer_running = False
            participation.timer_last_updated_at = None

        if participation.time_remaining_seconds <= 0:
            raise ValueError("Time limit exceeded for participation.")

        # Re-verify and deduct 1 credit upon final submission
        credit_result = await self.db.execute(
            select(ContestCredit).where(ContestCredit.customer_id == customer_id)
        )
        credit = credit_result.scalar_one_or_none()
        if not credit or credit.credits < 1.0:
            raise ValueError("Insufficient credits (1 Credit required) to submit entry.")

        credit.credits = round(float(credit.credits) - 1.0, 2)

        participation.text_content = text_content
        participation.media_url = media_url
        participation.is_submitted = True

        await self.db.commit()
        await self.db.refresh(participation)
        return participation

    async def cancel_participation(self, participation_id: uuid.UUID, customer_id: uuid.UUID) -> bool:
        result = await self.db.execute(
            select(ContestParticipation).where(
                ContestParticipation.id == participation_id,
                ContestParticipation.customer_id == customer_id
            )
        )
        participation = result.scalar_one_or_none()
        if not participation:
            return True

        if participation.is_submitted:
            raise ValueError("Cannot cancel an entry that has already been submitted.")

        await self.db.delete(participation)
        await self.db.commit()
        return True

    async def like_participation(self, participation_id: uuid.UUID, customer_id: uuid.UUID) -> bool:
        # Check participation exists
        part_result = await self.db.execute(
            select(ContestParticipation).where(ContestParticipation.id == participation_id)
        )
        participation = part_result.scalar_one_or_none()
        if not participation:
            raise NotFoundException("Participation not found.")

        # Check if already liked
        like_result = await self.db.execute(
            select(ContestLike).where(
                ContestLike.participation_id == participation_id,
                ContestLike.customer_id == customer_id
            )
        )
        like = like_result.scalar_one_or_none()

        if like:
            # Unlike
            await self.db.delete(like)
            participation.likes_count = max(0, participation.likes_count - 1)
            liked = False
        else:
            # Like
            new_like = ContestLike(participation_id=participation_id, customer_id=customer_id)
            self.db.add(new_like)
            participation.likes_count += 1
            liked = True

        await self.db.commit()
        await self.db.refresh(participation)
        return liked

    async def get_participations(self, contest_id: uuid.UUID) -> List[ContestParticipation]:
        result = await self.db.execute(
            select(ContestParticipation)
            .where(ContestParticipation.contest_id == contest_id, ContestParticipation.is_submitted == True)
            .options(selectinload(ContestParticipation.customer))
            .order_by(
                ContestParticipation.likes_count.desc(),
                ContestParticipation.comments_count.desc(),
                ContestParticipation.time_remaining_seconds.desc(),
                ContestParticipation.created_at.asc()
            )
        )
        participations = result.scalars().all()
        # Set transient/customer name property on responses
        for p in participations:
            if p.customer:
                p.customer_name = p.customer.name or p.customer.mobile_number
        return list(participations)

    async def get_winners(self, contest_id: uuid.UUID) -> List[ContestParticipation]:
        # Return all submissions ordered by likes count
        return await self.get_participations(contest_id)

    async def add_comment(self, participation_id: uuid.UUID, customer_id: uuid.UUID, text: str) -> ContestComment:
        # Check participation exists
        part_result = await self.db.execute(
            select(ContestParticipation).where(ContestParticipation.id == participation_id)
        )
        participation = part_result.scalar_one_or_none()
        if not participation:
            raise NotFoundException("Participation not found.")

        comment = ContestComment(participation_id=participation_id, customer_id=customer_id, text=text)
        self.db.add(comment)
        participation.comments_count = (participation.comments_count or 0) + 1
        await self.db.commit()
        await self.db.refresh(comment)
        
        # Load customer details
        res = await self.db.execute(
            select(ContestComment)
            .where(ContestComment.id == comment.id)
            .options(selectinload(ContestComment.customer))
        )
        return res.scalar_one()

    async def get_comments(self, participation_id: uuid.UUID, customer_id: Optional[uuid.UUID] = None) -> List[ContestComment]:
        result = await self.db.execute(
            select(ContestComment)
            .where(ContestComment.participation_id == participation_id)
            .options(selectinload(ContestComment.customer))
            .order_by(ContestComment.created_at.asc())
        )
        comments = list(result.scalars().all())
        
        if customer_id:
            liked_result = await self.db.execute(
                select(ContestCommentLike.comment_id)
                .join(ContestComment, ContestComment.id == ContestCommentLike.comment_id)
                .where(
                    ContestComment.participation_id == participation_id,
                    ContestCommentLike.customer_id == customer_id
                )
            )
            liked_comment_ids = {c_id for c_id in liked_result.scalars().all()}
            for c in comments:
                c.is_liked = c.id in liked_comment_ids
        else:
            for c in comments:
                c.is_liked = False
                
        return comments

    async def like_comment(self, comment_id: uuid.UUID, customer_id: uuid.UUID) -> bool:
        # Check comment exists
        result = await self.db.execute(
            select(ContestComment).where(ContestComment.id == comment_id)
        )
        comment = result.scalar_one_or_none()
        if not comment:
            raise NotFoundException("Comment not found.")

        # Check if already liked
        like_result = await self.db.execute(
            select(ContestCommentLike).where(
                ContestCommentLike.comment_id == comment_id,
                ContestCommentLike.customer_id == customer_id
            )
        )
        like = like_result.scalar_one_or_none()

        if like:
            # Unlike
            await self.db.delete(like)
            comment.likes_count = max(0, comment.likes_count - 1)
            liked = False
        else:
            # Like
            new_like = ContestCommentLike(comment_id=comment_id, customer_id=customer_id)
            self.db.add(new_like)
            comment.likes_count += 1
            liked = True

        await self.db.commit()
        return liked
