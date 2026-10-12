// 사용자에게 보이는 문구는 이 파일에만 둔다(IMPL-PLAN-9-parallel §5). 격식체, 용어표(회의·회의록·녹음·전사문·진행자·참여자).
// Sol이 문구만 다시 쓴다 — 키 이름과 인자는 바꾸지 않는다.
const mention = (id) => `<@${id}>`;

export const NICK_RECORDING = '[녹음중] 유달리';
export const TRANSCRIBE_FAILED = '[전사 실패]';

// 음성 채널 텍스트 채팅 고지
export const started = ({ hostId, maxMinutes, siteUrl }) =>
  `회의 녹음을 시작했습니다(진행자: ${mention(hostId)}). 이 채널에 머무르면 녹음·전사에 동의한 것으로 봅니다. ` +
  `참여를 원하지 않으면 채널에서 나가 주세요. 종료는 /회의종료, 최대 ${maxMinutes}분입니다.` +
  (siteUrl ? ` 처리방침: ${siteUrl.replace(/\/$/, '')}/privacy` : '');
export const joined = ({ userId }) =>
  `${mention(userId)} 님, 이 채널은 회의 녹음 중입니다. 머무르면 녹음·전사에 동의한 것으로 봅니다.`;
export const maxWarning = ({ maxMinutes }) =>
  `회의 최대 길이(${maxMinutes}분)까지 5분 남았습니다. 5분 뒤 녹음을 자동으로 종료합니다.`;
export const ended = ({ minutes, count }) =>
  `회의 녹음을 마쳤습니다(${minutes}분, 참여자 ${count}명). 회의록 초안이 준비되면 진행자에게 알려 드립니다.`;
export const lost = () =>
  '음성 연결이 끊겨 회의 녹음을 종료했습니다. 지금까지의 내용으로 회의록을 만듭니다.';
export const restarted = () => '녹음이 중단되어 지금까지의 내용으로 회의록을 만듭니다.';

// 내부 HTTP 오류 detail(Python 봇이 실행자에게 그대로 보인다)
export const notInVoice = () => '먼저 음성 채널에 들어간 뒤 /회의시작 을 눌러 주세요.';
export const alreadyRunning = () => '이 Discord 서버에서는 이미 회의가 진행 중입니다.';
export const joinFailed = () => '음성 채널에 접속하지 못해 회의를 시작하지 못했습니다. 잠시 뒤 다시 시도해 주세요.';
export const coreDown = () => '유달리 서버에 연결할 수 없습니다. 잠시 뒤 다시 시도해 주세요.';
export const noMeeting = () => '진행 중인 회의가 없습니다.';
export const unauthorized = () => '인증이 필요합니다.';
export const badRequest = () => '요청 형식이 올바르지 않습니다.';
export const notFound = () => '찾을 수 없는 경로입니다.';
