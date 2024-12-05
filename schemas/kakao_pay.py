from pydantic import BaseModel


class KakaoPayReady(BaseModel):
    cid: str
    partner_order_id: str
    partner_user_id: str
    item_name: str
    quantity: int
    total_amount: int
    tax_free_amount: int
    approval_url: str
    cancel_url: str
    fail_url: str


class KakaoPayApprove(BaseModel):
    cid: str
    tid: str
    partner_order_id: str
    partner_user_id: str
    pg_token: str
