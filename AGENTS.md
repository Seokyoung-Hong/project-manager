# Agent Instructions

작업을 시작하기 전에 현재 실행 모델에 맞는 instruction 파일을 반드시 읽고, 해당 지침에 따라 작업한다.

- Sol 또는 Sol 5.6 모델은 [`agent/sol-5.6.md`](agent/sol-5.6.md)를 읽고 수행한다.
- Astra 또는 Astra 6 모델은 [`agent/astra-6.md`](agent/astra-6.md)를 읽고 수행한다.

모델명에 맞는 instruction을 읽은 뒤에는 이 파일의 공통 지침과 해당 모델별 지침을 함께 준수한다.

모든 코드와 문서 변경은 독립적인 작업 단위가 끝날 때마다 검증하고, 변경사항을 별도의 Git 커밋으로 남긴다.

UI/UX 변경은 같은 화면과 viewport의 수정 전·후 캡처 및 근거 요약을 저장소에 남기고, 해당 소스 변경과 같은 Git 커밋에 포함해 커밋만으로 결과를 비교할 수 있게 한다.
