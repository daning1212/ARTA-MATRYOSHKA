# Healing Arty & Arta 공동개발

## ARTA MATRYOSHKA — 아르타 쉴드 🛡️

공격 도구를 누구나 구할 수 있다면 방어 실험 도구도 누구나 사용할 수 있어야 합니다.
ARTA는 **일관된 가짜 세계에서 탐색과 재검증 비용을 연구하는 로컬 HTTP 실험실**입니다.
운영 보안 제품이 아닙니다. AI를 속이는 효과와 지연 시간은 아직 측정하지 않았습니다.

## 실행

Python 3.10 이상. 추가 패키지 불필요.

```bash
git clone https://github.com/daning1212/ARTA-MATRYOSHKA-.git
cd ARTA-MATRYOSHKA-
python -m arta
```

- 미끼: http://127.0.0.1:8080 (JSON API)
- 관측: 127.0.0.1:8081 (Bearer 인증 필수)
- 기록 조회: 다른 터미널에서 `python -m arta.observe`
- 기록 검사: `python -m arta.observe --health`
- 종료: Ctrl+C

미끼와 수집기는 별도 프로세스로 실행됩니다. 양쪽 모두 localhost에만 바인딩됩니다.
인터넷이나 리버스 프록시로 공개하지 마세요. 관측 토큰은 `data/monitor-token`에 저장되며
관측 CLI가 읽습니다. 토큰을 URL, 스크린샷, GitHub에 올리지 마세요.
`--data-dir`을 바꿨다면 관측 CLI에도 동일한 값을 전달하세요.

## 가짜 세계

입구 `/` → 관리자 `/admin` 또는 백업 `/backup` → 진단 `/diagnostics` 또는 복구 `/recovery`
→ 작업 공간 `/workspace` → 설정 `/api/settings`.

작업 공간은 처음에 403을 반환합니다. 백업의 **가짜 복구 코드**를 `/recovery`에 POST하면
가짜 상태가 `sandbox`에서 `workspace`로 바뀌며 작업 공간 접근이 허용됩니다.
이것은 실제 샌드박스 탈출이나 실제 권한 상승이 아닙니다.
잘못된 코드는 항상 거부되며 다른 세션의 코드도 사용할 수 없습니다.
설정 변경은 같은 세션에서 재조회해도 유지됩니다.

```bash
curl -c cookies.txt http://127.0.0.1:8080/backup
# 위 JSON의 recovery_code를 아래 값으로 사용하세요.
curl -b cookies.txt -H 'Content-Type: application/json' \
  -d '{"recovery_code":"PASTE_CODE"}' http://127.0.0.1:8080/recovery
curl -b cookies.txt http://127.0.0.1:8080/workspace
curl -b cookies.txt -H 'Content-Type: application/json' \
  -d '{"maintenance":true}' http://127.0.0.1:8080/api/settings
curl -b cookies.txt http://127.0.0.1:8080/api/settings
```

실험 후 `cookies.txt`를 삭제하세요. 세션은 15분 또는 세계 요청 100회로 제한됩니다.
재시작하면 가짜 세계는 초기화됩니다. 새 세션으로 예산을 초기화할 수 있으므로
이 예산은 전역 공격 차단 장치가 아닙니다.

## 기록과 상한

- IP당 60초에 30회 요청, 본문 4 KiB, 경로 2 KiB, 세션·클라이언트 각각 1,000개.
- 알려진 방 이름, IP, 수집 시간, 응답 상태, 세션 해시, 세계 전이, 단계 수 기록.
- 본문·쿼리·인증 헤더·원본 쿠키·복구 코드 기록 제외.
- 별도 수집기로 인증된 최대 2 KiB JSON UDP 메시지 전달. 객체 역직렬화 없음.
- 수집기가 보관하는 최근 10,000개 이벤트 중 최근 100개를 관측 API로 조회.
- 인증 실패·형식 오류·저장 오류 관련 수집기 카운터 제공.

UDP 전송은 최선형 전달이며 전달 보장이 아닙니다. 수집기 종료·버퍼 초과·프로세스 종료 때
이벤트가 유실될 수 있습니다. 송신 오류 감지 카운터는 콘솔에 표시하지만 모든 유실을 알 수는 없습니다.

## 보안 한계

**별도 프로세스는 강력한 격리가 아닙니다.** 기본 실행은 같은 OS 계정입니다.
미끼 코드 실행이 장악되면 그 계정이 읽을 수 있는 기록·토큰·호스트 파일도 위험합니다.
기록 전달 전용 토큰과 관측 토큰은 다르지만 파일 권한은 다른 OS 계정만 제한합니다.
미끼의 실제 서버 접근·외부 통신을 OS 수준에서 차단하는 기능은 아직 없습니다.

기록 해시는 일부 변조를 감지할 뿐, 전체 재작성·삭제를 막거나 증명하지 않습니다.
이벤트는 미끼가 보고한 데이터이므로 미끼가 장악되면 위조 가능합니다.
순차 HTTP 처리와 UDP 수집은 폭주·느린 연결 공격에 충분한 방어가 아닙니다.
로그 개수 제한은 장기 디스크 공간의 엄격한 상한이 아닙니다.

실제 로그인 보호, 분산 공격 대응, 와이파이 보안, DDoS 방어, 두 사람 승인,
계산 통행료·VDF, 외부 알림, 시각적 대시보드는 미구현입니다.
실제 비밀·개인정보를 넣지 말고 허가된 격리 실험 환경에서만 사용하세요.

## 테스트와 문서

```bash
python -m unittest discover -s tests -v
```

- [설계와 AI 실험 계획](docs/DESIGN.md)
- [현재 개발 보고서와 자체 문답](docs/REPORT.md)

MIT License. 개선 제안과 기여를 환영합니다.
