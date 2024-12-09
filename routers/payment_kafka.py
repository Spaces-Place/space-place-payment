from datetime import datetime
import json
from typing import Dict
from fastapi import APIRouter, Depends, HTTPException, Header, Query, status
import httpx

from enums.payment_type import PaymentStatus
from models.payment import Payment
from schemas.common import BaseResponse
from schemas.kakao_pay import KakaoPayApprove, KakaoPayReady
from schemas.payment import PaymentApproveResponse, KakaoReadyRequest
from services.payment_service import PaymentService, get_payment_service
from utils.authenticate import userAuthenticate
from utils.aws_ssm import ParameterStore
from utils.logger import Logger
from utils.mysqldb import get_mysql_session
import os
from sqlmodel import select

from utils.service_url import ServiceUrlConfig
from schemas.kakao_pay import KakaoPayFail


payment_kafka_router = APIRouter(tags=["결제"])

# 결제 요청
@payment_kafka_router.post(
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
    logger: Logger = Depends(Logger.setup_logger),
    payment_service: PaymentService = Depends(get_payment_service),
    authorization: str = Header(None)
):
    """구현이 필요하지 않습니다."""
    member_url = service_urls.member_url
    reservation_url = service_urls.reservation_url
    payment_url = service_urls.payment_url
    space_url = service_urls.space_url
    space_domain = service_urls.space_domain
    api_domain = service_urls.api_domain
    kakaopay_url = os.getenv("KAKAOPAY_URL")
    kakao_secret_key = parameter_store.get_parameter("KAKAO_SECRET_KEY", True)
    user_id = token_info["user_id"]
    user_token = authorization.split(" ")[1]


    logger.info(f"예약 및 결제 준비 요청: {user_id}")

    """
    회원: 결제자 정보 요청
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{member_url}/members/{user_id}",
                headers={
                    "Authorization": f"Bearer {user_token}",
                    "Content-Type": "application/json"
                }
            )
            response.raise_for_status()
            response_data=response.json()
            user_name=response_data.get("name")

    except Exception as e:
        logger.error(f'회원 정보를 가져올 수 없습니다: {e}')
        raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="결제 중 오류가 발생했습니다.",
            )
    


    """
    공간: 이름, 가격 정보 받아오기
    (space_id, use_date, start_time, end_time) -> (space_name, total_amount, quantity)
    """
    try:
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
    except Exception as e:
        logger.error(f'공간 정보를 가져올 수 없습니다: {e}')
        raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="결제 중 오류가 발생했습니다.",
            )



    """
    예약: 예약 정보 저장, 예약 번호 응답
    """
    reservation_data = payment_request.model_dump()
    reservation_data["user_name"] = user_name
    reservation_data["space_name"] = space_name
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{reservation_url}/reservations/kakao/ready",
                data=json.dumps(reservation_data, ensure_ascii=False),
                headers={
                    "Authorization": f"Bearer {user_token}",
                    "Content-Type": "application/json"
                }
            )
            response.raise_for_status()
            response_data=response.json()
            order_number=response_data.get("order_number")
    except Exception as e:
        logger.error(f'예약 번호를 가져올 수 없습니다: {e}')
        raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="결제 중 오류가 발생했습니다.",
            )

    """
    카카오: 카카오 결제 준비
    """
    payment_data = KakaoPayReady(
    cid= 'TC0ONETIME',
    partner_order_id= order_number,
    partner_user_id= user_id,
    item_name= space_name,
    quantity= int(quantity),
    total_amount= int(total_amount),
    tax_free_amount= int(total_amount),
    approval_url= f"{space_domain}/booking/success?order_number={order_number}",
    cancel_url= f"{space_domain}/booking/cancel?order_number={order_number}",
    fail_url= f"{space_domain}/booking/fail?order_number={order_number}"
    # approval_url= f"{payment_url}/payments/kakao/approval?order_number={order_number}",
    # cancel_url= f"{payment_url}/payments/kakao/cancel?order_number={order_number}",
    # fail_url= f"{payment_url}/payments/kakao/fail?order_number={order_number}"
    )

    logger.info(f'카카오 결제 준비 요청: {payment_data}')
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{kakaopay_url}/online/v1/payment/ready",
                data=payment_data.model_dump_json(),
                headers={
                    "Authorization": f"SECRET_KEY {kakao_secret_key}",
                    "Content-Type": "application/json"
                }
            )
            response.raise_for_status()
            ready_completed_result=response.json()
            next_redirect_pc_url = ready_completed_result.get('next_redirect_pc_url')
            tid=ready_completed_result.get('tid')
            logger.info(f'카카오 결제 준비 성공: {ready_completed_result}')
        
    except Exception as e:
        logger.error(f'카카오 결제 준비 중 오류가 발생했습니다.: {e}')
        raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="결제 중 오류가 발생했습니다.",
            )

    # tid 포함된 결제 정보 저장
    new_payment = Payment(
        space_id = payment_request.space_id,
        space_name = space_name,
        user_id = user_id,
        user_name = user_name,
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

    """
    예약: payment_id 저장
    """
    try:
        # 객체를 그냥 보내게 되면 '키':'값'으로 가게 되는 문제 발생 
        # '키'는 json 타입으로 인식하지 못해 "키"로 갈 수 있게 json string으로 먼저 변환함.
        ready_approval_data = {
            "payment_id": payment_id,
            "order_number": order_number
        }
        await payment_service.ready_approval(json.dumps(ready_approval_data))
    except Exception as e:
        logger.error(f"예약 서비스 payment_id 업데이트 토픽 발행 중 오류 발생.{e}")
        raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="결제 중 오류가 발생했습니다.",
            )
    
    logger.info(f"예약 및 결제 준비 완료: {user_id}:{order_number}")
    # 사용자에게 결제 화면 보냄
    return {"next_redirect_pc_url": next_redirect_pc_url}



# 결제 승인
@payment_kafka_router.get(
    "/kakao/approval",
    response_model=PaymentApproveResponse,
    status_code=status.HTTP_200_OK,
    summary="결제 승인"
)
async def payment_approve(
    order_number: str,
    pg_token: str,
    payment_service: PaymentService = Depends(get_payment_service),
    service_urls: ServiceUrlConfig = Depends(ServiceUrlConfig),
    parameter_store: ParameterStore = Depends(ParameterStore),
    session=Depends(get_mysql_session),
    token_info=Depends(userAuthenticate),
    logger: Logger = Depends(Logger.setup_logger),
    authorization: str = Header(None)
):
    kakao_secret_key = parameter_store.get_parameter("KAKAO_SECRET_KEY", True)
    reservation_url = service_urls.reservation_url
    kakaopay_url = os.getenv("KAKAOPAY_URL")
    user_id = token_info["user_id"]
    # user_id = "test_consumer"
    user_token = authorization.split(" ")[1]

    logger.info(f"예약 및 결제 승인 요청: {user_id}")

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

    logger.info(f'카카오 결제 승인 요청: {kakaopay_url}')
    try:
        # 카카오: 결제 승인
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{kakaopay_url}/online/v1/payment/approve",
                data=approve_data.model_dump_json(),
                headers={
                    "Authorization": f"SECRET_KEY {kakao_secret_key}",
                    "Content-Type": "application/json"
                }
            )
            response.raise_for_status()
            approval_result=response.json()
            payment_method_type = approval_result.get("payment_method_type")
            amount = approval_result.get("amount").get("total")

            logger.info(f'카카오 결제 승인 완료: {approval_result}')
    except Exception as e:
        logger.error(f'카카오 결제 승인 요청에 실패했습니다:{e}')
        raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="결제 중 오류가 발생했습니다.",
            )
    
    # 여기까지 결제 승인된 상태
    payment_approval_data = {"order_number": order_number}
    await payment_service.payment_approval(json.dumps(payment_approval_data))

    logger.info(f"예약 및 결제 승인 성공: {user_id}")

    return PaymentApproveResponse(
        message="예약 및 결제가 완료되었습니다.",
        order_number=order_number
    )


# 결제 실패
@payment_kafka_router.post(
    "/kakao/fail",
    response_model=BaseResponse,
    status_code=status.HTTP_200_OK,
    summary="결제 실패"
)
async def payment_fail(
    fail_data: KakaoPayFail,
    payment_service: PaymentService = Depends(get_payment_service),
    session=Depends(get_mysql_session),
    service_urls: ServiceUrlConfig = Depends(ServiceUrlConfig),
    token_info=Depends(userAuthenticate),
    logger: Logger = Depends(Logger.setup_logger),
    authorization: str = Header(None)
):
    """구현이 필요하지 않습니다."""
    reservation_url = service_urls.reservation_url
    user_token = authorization.split(" ")[1]
    user_id = token_info["user_id"]

    logger.info(f"예약 및 결제 실패 처리: {user_id}")

    statement = select(Payment).filter(Payment.order_number == fail_data.order_number)
    result = await session.execute(statement)
    payment = result.scalars().first()

    if not payment:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="잘못된 접근입니다.",
        )
    
    payment.p_status = PaymentStatus.FAILED
    await session.commit()

    # 결제 실패
    await payment_service.ready_fail(json.dumps({"order_number": fail_data.order_number}))

    return BaseResponse(message="예약 및 결제가 실패했습니다.")


# 결제 취소
@payment_kafka_router.post(
    "/kakao/cancel",
    response_model=BaseResponse,
    status_code=status.HTTP_200_OK,
    summary="결제 취소"
)
async def payment_approve(
    order_number: str,
    session=Depends(get_mysql_session),
    service_urls: ServiceUrlConfig = Depends(ServiceUrlConfig),
    token_info=Depends(userAuthenticate),
    logger: Logger = Depends(Logger.setup_logger),
    authorization: str = Header(None)
):
    """구현이 필요하지 않습니다."""
    reservation_url = service_urls.reservation_url
    user_token = authorization.split(" ")[1]
    user_id = token_info["user_id"]

    logger.info(f"결제 취소 처리: {user_id}")

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
    logger.info('예약 상태 CANCELED 업데이트 요청')
    try:
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
            logger.info('예약 상태 CANCELED 업데이트 성공')
    except Exception as e:
        logger.error(f'예약 상태 CANCELED 업데이트 실패: {e}')
        raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="결제 중 오류가 발생했습니다.",
            )

    return BaseResponse(message="예약 및 결제가 취소되었습니다.")

@payment_kafka_router.get(
    "",
    response_model=Dict,
    status_code=status.HTTP_200_OK,
    summary="결제 내역 확인"
)
async def get_reservations(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    session=Depends(get_mysql_session),
    token_info=Depends(userAuthenticate),
    logger: Logger = Depends(Logger.setup_logger)
):
    statement = select(Payment).where(Payment.user_id == token_info["user_id"]).offset(skip).limit(limit)
    result = await session.execute(statement)
    reservations = result.scalars().all()

    if reservations:
        logger.info("결제 내역 확인 성공")

    return {"reservations": reservations}