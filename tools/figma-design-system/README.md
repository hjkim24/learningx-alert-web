# LearningX Alert Design System (Figma 플러그인)

[DESIGN.md](../../DESIGN.md)의 토큰으로 Figma 파일에 디자인 시스템을 만드는 개발용 플러그인입니다. 네트워크에 접속하지 않고, 실행한 파일 안에서만 작업합니다.

## 만드는 것

- **Variables:** `LearningX Alert` 컬렉션에 색(`color/brand|neutral|status/*`), 간격(`space/*`), 모서리(`radius/*`)
- **스타일:** 색 스타일(변수에 연결), 텍스트 스타일 6개, 그림자 스타일 2개(`shadow-sheet`, `shadow-float`)
- **페이지:** `LearningX Design System` 페이지에 색 견본, 타이포그래피, 간격·모서리, 컴포넌트(버튼 3종, 배지 4종, 토글, 안내 상자, 토스트, 입력칸)

다시 실행하면 변수와 스타일은 같은 이름으로 값만 바꾸고, `LearningX Design System` 페이지는 새로 만듭니다. 다른 페이지는 건드리지 않습니다. 그 페이지에서 직접 고친 내용은 다시 실행하면 사라집니다.

## 실행

1. Figma 데스크톱 앱에서 디자인 파일을 엽니다.
2. **Plugins -> Development -> Import plugin from manifest...**에서 이 폴더의 `manifest.json`을 고릅니다.
3. **Plugins -> Development -> LearningX Alert Design System**을 실행합니다.

글꼴은 Pretendard, Apple SD Gothic Neo, Noto Sans KR, Inter 순서로 설치된 것을 씁니다.

## 토큰 바꾸기

색을 바꿀 때는 DESIGN.md, `static/app.css`, 이 폴더의 `code.js` 맨 위 `TOKENS`를 함께 고칩니다. `accounts/tests/test_design_tokens.py`가 세 곳의 색이 같은지 확인합니다.
