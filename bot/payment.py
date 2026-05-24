"""
Payment Processing Module
Handles Stripe payments and subscriptions
"""
import stripe
import logging
from config import STRIPE_API_KEY, STRIPE_PUBLIC_KEY, PREMIUM_PRICE_USD, PREMIUM_PRICE_INR
from database.connection import Database
from datetime import datetime, timedelta
import uuid

logger = logging.getLogger(__name__)

# Initialize Stripe
stripe.api_key = STRIPE_API_KEY


class PaymentManager:
    """Payment and Subscription Management"""
    
    @staticmethod
    async def create_customer(
        user_id: int,
        email: str,
        name: str
    ) -> Optional[str]:
        """
        Create Stripe customer
        
        Args:
            user_id: Telegram user ID
            email: Customer email
            name: Customer name
            
        Returns:
            Stripe customer ID or None if failed
        """
        try:
            customer = stripe.Customer.create(
                email=email,
                name=name,
                metadata={"telegram_user_id": str(user_id)}
            )
            
            logger.info(f"✅ Stripe customer created: {customer.id}")
            return customer.id
            
        except stripe.error.StripeError as e:
            logger.error(f"❌ Stripe error: {e}")
            return None
    
    @staticmethod
    async def create_payment_intent(
        user_id: int,
        amount: int,  # in cents
        currency: str = "usd",
        description: str = ""
    ) -> Optional[dict]:
        """
        Create Stripe payment intent
        
        Args:
            user_id: Telegram user ID
            amount: Amount in cents (e.g., 399 for $3.99)
            currency: Currency code
            description: Payment description
            
        Returns:
            Payment intent data or None if failed
        """
        try:
            intent = stripe.PaymentIntent.create(
                amount=amount,
                currency=currency,
                description=description,
                metadata={"telegram_user_id": str(user_id)}
            )
            
            logger.info(f"✅ Payment intent created: {intent.id}")
            return {
                "id": intent.id,
                "client_secret": intent.client_secret,
                "amount": intent.amount,
                "currency": intent.currency,
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"❌ Stripe error: {e}")
            return None
    
    @staticmethod
    async def create_subscription(
        user_id: int,
        stripe_customer_id: str,
        plan: str = "premium_monthly"
    ) -> Optional[dict]:
        """
        Create subscription
        
        Args:
            user_id: Telegram user ID
            stripe_customer_id: Stripe customer ID
            plan: Subscription plan
            
        Returns:
            Subscription data or None if failed
        """
        try:
            # Create or get product and price
            product = stripe.Product.create(
                name=f"GFX Bot - {plan.replace('_', ' ').title()}",
            )
            
            price = stripe.Price.create(
                product=product.id,
                unit_amount=int(PREMIUM_PRICE_USD * 100),  # Convert to cents
                currency="usd",
                recurring={
                    "interval": "month",
                    "interval_count": 1,
                }
            )
            
            subscription = stripe.Subscription.create(
                customer=stripe_customer_id,
                items=[{"price": price.id}],
                metadata={"telegram_user_id": str(user_id)},
            )
            
            logger.info(f"✅ Subscription created: {subscription.id}")
            return {
                "id": subscription.id,
                "customer_id": subscription.customer,
                "status": subscription.status,
                "current_period_start": subscription.current_period_start,
                "current_period_end": subscription.current_period_end,
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"❌ Stripe error: {e}")
            return None
    
    @staticmethod
    async def verify_payment(payment_intent_id: str) -> bool:
        """
        Verify payment status
        
        Args:
            payment_intent_id: Stripe payment intent ID
            
        Returns:
            True if payment succeeded, False otherwise
        """
        try:
            intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            
            if intent.status == "succeeded":
                logger.info(f"✅ Payment verified: {payment_intent_id}")
                return True
            
            logger.warning(f"⚠️ Payment not succeeded: {intent.status}")
            return False
            
        except stripe.error.StripeError as e:
            logger.error(f"❌ Stripe error: {e}")
            return False
    
    @staticmethod
    async def cancel_subscription(subscription_id: str) -> bool:
        """
        Cancel subscription
        
        Args:
            subscription_id: Stripe subscription ID
            
        Returns:
            True if cancelled successfully
        """
        try:
            stripe.Subscription.delete(subscription_id)
            logger.info(f"✅ Subscription cancelled: {subscription_id}")
            return True
        except stripe.error.StripeError as e:
            logger.error(f"❌ Stripe error: {e}")
            return False
    
    @staticmethod
    async def get_subscription_status(subscription_id: str) -> Optional[dict]:
        """Get subscription status"""
        try:
            subscription = stripe.Subscription.retrieve(subscription_id)
            return {
                "status": subscription.status,
                "current_period_start": subscription.current_period_start,
                "current_period_end": subscription.current_period_end,
                "cancel_at": subscription.cancel_at,
            }
        except stripe.error.StripeError as e:
            logger.error(f"❌ Stripe error: {e}")
            return None
    
    @staticmethod
    async def record_payment(
        user_id: int,
        amount: float,
        stripe_payment_id: str,
        status: str = "succeeded"
    ) -> Optional[str]:
        """
        Record payment in database
        
        Args:
            user_id: Telegram user ID
            amount: Payment amount
            stripe_payment_id: Stripe payment ID
            status: Payment status
            
        Returns:
            Payment ID or None if failed
        """
        try:
            db = Database.get_database()
            
            payment_data = {
                "payment_id": str(uuid.uuid4()),
                "user_id": user_id,
                "stripe_payment_id": stripe_payment_id,
                "amount": amount,
                "currency": "USD",
                "status": status,
                "plan": "premium_monthly",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
            
            result = await db["payments"].insert_one(payment_data)
            logger.info(f"✅ Payment recorded: {payment_data['payment_id']}")
            return payment_data["payment_id"]
            
        except Exception as e:
            logger.error(f"❌ Error recording payment: {e}")
            return None
    
    @staticmethod
    async def activate_premium(
        user_id: int,
        days: int = 30
    ) -> bool:
        """
        Activate premium subscription for user
        
        Args:
            user_id: Telegram user ID
            days: Subscription duration in days
            
        Returns:
            True if activated successfully
        """
        try:
            db = Database.get_database()
            
            expires_at = datetime.utcnow() + timedelta(days=days)
            
            result = await db["users"].update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "role": "premium",
                        "subscription.status": "active",
                        "subscription.plan": "premium",
                        "subscription.started_at": datetime.utcnow(),
                        "subscription.expires_at": expires_at,
                    }
                }
            )
            
            logger.info(f"✅ Premium activated for user {user_id} until {expires_at}")
            return result.modified_count > 0
            
        except Exception as e:
            logger.error(f"❌ Error activating premium: {e}")
            return False


from typing import Optional
