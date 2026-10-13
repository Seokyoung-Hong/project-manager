"""내 PC 거쳐 보내기(IMPL-PLAN-12 §5.3·§6.2·§6.3). 몸체는 D 갈래."""


def on_heartbeat(server, data: dict) -> dict:
    """notes.stt_link.heartbeat() 끝에서 부른다: out.update(on_heartbeat(server, data)).

    data에 ai=1이고 ai_job_id가 비면 {"ai_job": {id, url, model, api_key, messages, max_tokens,
    temperature, response_format, timeout_s}}, 보고한 ai_job_id가 cancelling이면 {"ai_cancel": True}.
    배정은 server.owner_id == job.user_id인 작업만(불변식 2). 줄 것이 없으면 {}.
    """
    raise NotImplementedError


def report(job_id: int, server, data: dict):
    """PATCH /api/integrations/stt/ai-jobs/{id}. data = SttAiReportIn.dict().

    job.server == server이고 그 주인 == 요청자일 때만(아니면 Http404), 끝난 작업이면 409.
    """
    raise NotImplementedError
