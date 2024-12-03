from datetime import datetime
import json
from typing import Dict
from fastapi import APIRouter, Depends, HTTPException, Header, status
import httpx

from enums.payment_type import PaymentStatus
from models.payment import Payment
from schemas.common import BaseResponse
from schemas.kakao_pay import KakaoPayApprove, KakaoPayReady
from schemas.payment import PaymentApproveResponse, KakaoReadyRequest
from utils.authenticate import userAuthenticate
from utils.aws_ssm import ParameterStore
from utils.mysqldb import get_mysql_session
import os
from sqlmodel import select

from utils.service_url import ServiceUrlConfig


payment_router = APIRouter(tags=["결제"])


# 결제 요청
@payment_router.post(
    "/kakao",
    response_model=Dict,
    status_code=status.HTTP_200_OK,
    summary="결제 준비"
)
async def payment_ready(
    payment_request: KakaoReadyRequest,
    service_urls: ServiceUrlConfig = Depends(ServiceUrlConfig),
    parameter_store: ParameterStore = Depends(ParameterStore),
    session=Depends(get_mysql_session),
    token_info=Depends(userAuthenticate),
    authorization: str = Header(None)
):
    """구현이 필요하지 않습니다."""
    reservation_url = service_urls.reservation_url
    payment_url = service_urls.payment_url
    space_url = service_urls.space_url
    kakaopay_url = os.getenv("KAKAOPAY_URL")
    kakao_secret_key = parameter_store.get_parameter("KAKAO_SECRET_KEY", True)
    user_id = token_info["user_id"]
    user_token = authorization.split(" ")[1]


    # 예약: 예약 번호 요청
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{reservation_url}/reservations/kakao/ready",
            data=json.dumps(payment_request.model_dump(), ensure_ascii=False),
            headers={
                "Authorization": f"Bearer {user_token}",
                "Content-Type": "application/json"
            }
        )
        response.raise_for_status()
        response_data=response.json()
        order_number=response_data.get("order_number")

    # 공간: 이름, 가격 정보 받아오기(space_id, use_date, start_time, end_time) -> (space_name, unit_price)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{space_url}/spaces/pre-order",
            data=json.dumps(payment_request.model_dump(), ensure_ascii=False),
            headers={
                "Authorization": f"Bearer {user_token}",
                "Content-Type": "application/json"
            }
        )
        response.raise_for_status()
        response_data=response.json()
        space_name=response_data.get("space_name")
        total_amount=response_data.get("total_amount")
        quantity=response_data.get("quantity")

    # 카카오: 카카오 결제 준비
    payment_data = KakaoPayReady(
    cid= 'TC0ONETIME',
    partner_order_id= order_number,
    partner_user_id= user_id,
    item_name= space_name,
    quantity= int(quantity),
    total_amount= int(total_amount),
    tax_free_amount= int(total_amount),
    approval_url= f"{payment_url}/payments/kakao/approval?order_number={order_number}",
    cancel_url= f"{payment_url}/payments/kakao/cancel?order_number={order_number}",
    fail_url= f"{payment_url}/payments/kakao/fail?order_number={order_number}"
    )

    try:
        async with httpx.AsyncClient() as client:
            # 요청 전 데이터 로깅
            print("Request data:", payment_data.model_dump())
            
            response = await client.post(
                f"{kakaopay_url}/online/v1/payment/ready",
                data=payment_data.model_dump_json(),
                headers={
                    "Authorization": f"SECRET_KEY {kakao_secret_key}",
                    "Content-Type": "application/json"
                }
            )
            
            if response.status_code != 200:
                # 에러 응답 내용 로깅
                error_content = await response.text()
                print("Error response:", error_content)
            
            response.raise_for_status()
            ready_completed_result = response.json()
            next_redirect_pc_url = ready_completed_result.get('next_redirect_pc_url')
            tid = ready_completed_result.get('tid')

    except httpx.HTTPError as e:
        error_detail = await e.response.text() if e.response else "No response"
        print(f"KakaoPay API Error: {error_detail}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"카카오페이 요청 실패: {error_detail}"
        )
        
    # tid 포함된 결제 정보 저장
    new_payment = Payment(
        space_id = payment_request.space_id,
        user_id = user_id,
        tid = tid,
        order_number = order_number, 
        p_status = PaymentStatus.PENDING,
        amount=total_amount,
        payment_date=datetime.now()
    )
    session.add(new_payment)
    await session.commit()
    await session.refresh(new_payment)
    payment_id = new_payment.id

    # 예약: payment_id 저장
    async with httpx.AsyncClient() as client:
        response = await client.patch(
            f"{reservation_url}/reservations/kakao/ready",
            json={"payment_id": payment_id, "order_number": order_number},
            headers={
                "Authorization": f"Bearer {user_token}",
                "Content-Type": "application/json"
            }
        )
        response.raise_for_status()
    
    # 사용자에게 결제 화면 보냄
    return {"next_redirect_pc_url": next_redirect_pc_url}


@payment_router.get(
    "/kakao/approval",
    response_model=PaymentApproveResponse,
    status_code=status.HTTP_200_OK,
    summary="결제 승인"
)
async def payment_approve(
    order_number: str,
    pg_token: str,
    session=Depends(get_mysql_session),
    token_info=Depends(userAuthenticate),
    authorization: str = Header(None)
):
    """구현이 필요하지 않습니다."""
    reservation_url = os.getenv("RESERVATION_URL")
    kakaopay_url = os.getenv("KAKAOPAY_URL")
    user_id = token_info["user_id"]
    user_token = authorization.split(" ")[1]

    statement = select(Payment).filter(Payment.order_number == order_number)
    result = await session.execute(statement)
    payment = result.scalars().first()

    if payment:
        tid = payment.tid
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="잘못된 접근입니다.",
        )
    
    approve_data = KakaoPayApprove(
        cid= 'TC0ONETIME',
        tid= tid,
        partner_order_id= order_number,
        partner_user_id= user_id,
        pg_token= pg_token,
    )

    # 카카오: 결제 승인
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{kakaopay_url}/online/v1/payment/approve",
            data=approve_data.model_dump_json(),
            headers={
                "Authorization": f"SECRET_KEY {os.getenv("KAKAO_SECRET_KEY")}",
                "Content-Type": "application/json"
            }
        )
        response.raise_for_status()
        approval_result=response.json()

    # 여기까지 결제 승인된 상태
    payment_method_type = approval_result.get("payment_method_type")
    amount = approval_result.get("amount").get("total")

    payment.payment_method = payment_method_type
    payment.amount = amount
    payment.p_status = PaymentStatus.COMPLETED
    await session.commit()

    # 예약: 예약 상태 업데이트
    async with httpx.AsyncClient() as client:
        response = await client.patch(
            f"{reservation_url}/reservations/kakao/approve",
            json={"order_number": order_number},
            headers={
                "Authorization": f"Bearer {user_token}",
                "Content-Type": "application/json"
            }
        )
        response.raise_for_status()

    return PaymentApproveResponse(
        message="예약 및 결제가 완료되었습니다.",
        order_number=order_number
    )


@payment_router.post(
    "/kakao/fail",
    response_model=BaseResponse,
    status_code=status.HTTP_200_OK,
    summary="결제 실패"
)
async def payment_approve(
    order_number: str,
    session=Depends(get_mysql_session),
    token_info=Depends(userAuthenticate),
    authorization: str = Header(None)
):
    """구현이 필요하지 않습니다."""
    reservation_url = os.getenv("RESERVATION_URL")
    user_token = authorization.split(" ")[1]

    statement = select(Payment).filter(Payment.order_number == order_number)
    result = await session.execute(statement)
    payment = result.scalars().first()

    if not payment:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="잘못된 접근입니다.",
        )
    
    payment.p_status = PaymentStatus.FAILED
    await session.commit()

    # 예약: 예약 상태 업데이트
    async with httpx.AsyncClient() as client:
        response = await client.patch(
            f"{reservation_url}/reservations/kakao/fail",
            json={"order_number": order_number},
            headers={
                "Authorization": f"Bearer {user_token}",
                "Content-Type": "application/json"
            }
        )
        response.raise_for_status()

    return BaseResponse(message="예약 및 결제가 실패했습니다.")


@payment_router.post(
    "/kakao/cancel",
    response_model=BaseResponse,
    status_code=status.HTTP_200_OK,
    summary="결제 취소"
)
async def payment_approve(
    order_number: str,
    session=Depends(get_mysql_session),
    token_info=Depends(userAuthenticate),
    authorization: str = Header(None)
):
    """구현이 필요하지 않습니다."""
    reservation_url = os.getenv("RESERVATION_URL")
    user_token = authorization.split(" ")[1]

    statement = select(Payment).filter(Payment.order_number == order_number)
    result = await session.execute(statement)
    payment = result.scalars().first()

    if not payment:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="잘못된 접근입니다.",
        )
    
    payment.p_status = PaymentStatus.FAILED
    await session.commit()

    # 예약: 예약 상태 업데이트
    async with httpx.AsyncClient() as client:
        response = await client.patch(
            f"{reservation_url}/reservations/kakao/cancel",
            json={"order_number": order_number},
            headers={
                "Authorization": f"Bearer {user_token}",
                "Content-Type": "application/json"
            }
        )
        response.raise_for_status()

    return BaseResponse(message="예약 및 결제가 취소되었습니다.")