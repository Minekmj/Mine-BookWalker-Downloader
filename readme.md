<div align="center">

<img src="https://raw.githubusercontent.com/Minekmj/Mine-BookWalker-Downloader/refs/heads/main/qss/icons/icon.png?v=2" width="128" height="128">

# MINE BOOKWALKER DOWNLOADER

<p>
  <a href="https://github.com/Minekmj/Mine-BookWalker-Downloader/releases/latest">
    <img src="https://img.shields.io/github/v/release/Minekmj/Mine-BookWalker-Downloader?display_name=tag&sort=date" alt="Latest Release">
  </a>

  <a href="https://github.com/Minekmj/Mine-BookWalker-Downloader/releases">
    <img src="https://img.shields.io/github/downloads/Minekmj/Mine-BookWalker-Downloader/total" alt="Downloads">
  </a>

  <a href="https://github.com/Minekmj/Mine-BookWalker-Downloader">
    <img src="https://img.shields.io/github/license/Minekmj/Mine-BookWalker-Downloader" alt="License">
  </a>

</p>

<p>
북워커의 라노벨과 만화를 찍어서<br>
Epub 혹은 Pdf로 변환하는 데스크톱 프로그램입니다.
</p>

</div>

## 소개

<b>MINE BOOKWALKER DOWNLOADER</b>는 일본 플렛폼 <b>BookWalker</b>의 작품을 번역하기 위하여 pdf 호은 epub으로 변환하는 프로젝트입니다.

웹에서 하나하나 스크린샷하며 다운로드하고 OCR하거나 모으는 과정을 단순화 할 수 있도록 제작되었습니다.

## 주요 기능

### 다운로드 스크립트 자동 생성

* 브라우저에서 화면을 찍을 때 사용되는 스크립트를 자동생성
* 간격을 조정가능하며 해상도 설정이 가능
* 화면을 자동으로 넘기며 촬영
* 화면 범위 사용자 지정

### 작품 다운로드 경로 제공

* 브라우저에서 다운로드를 시작하며 자동으로 작품 경로 생성

### 이미지 변환

* 스캔한 작품을 epub 혹은 pdf로 변환

* #### EPUB
* 제미나이로 자동으로 목차를 생성
* 삽화와 텍스트 분리 자동화
    * 사용자 지정 가능
* 제미나이로 OCR 분석
* 제미나이로 검수

* #### PDF & ZIP
* 이미지를 엮어서 제작


## 다운로드

### Windows EXE

Python이나 별도의 개발 환경을 설치하지 않고 바로 실행하려면 EXE 버전을 사용할 수 있습니다.

1. [최신 릴리스(Releases)](https://github.com/Minekmj/Mine-BookWalker-Downloader/releases) 페이지에서 최신 `.exe` 파일을 다운로드합니다.
2. 새로운 폴더를 만들고 거기에 다운받은 `.exe` 파일을 넣습니다.
3. `Mine BookWalker DownLoader.exe`를 실행합니다.

* 처음 실행 시 만일 에러 문제가 날 시, 윈도우에서 자동으로 바이너리 데이터를 지운 것으로 직접 환경을 세팅하여 아래 방법을 이용하세요.

<br/>

> ZIP 버전은 별도의 Python 설치 없이 사용할 수 있습니다.

<h2/>

## 설치 및 실행

현재 Windows 환경을 지원합니다.

### 요구 사항

* Windows
* Python 3.12 이상

### 1. 저장소 클론

```bash
git clone https://github.com/Minekmj/Mine-BookWalker-Downloader.git
cd Mine-BookWalker-Downloader
```

### 2. 가상환경 생성

Python 프로젝트의 독립적인 환경 구성을 위해 가상환경 사용을 권장합니다.

**Windows Command Prompt**

```bash
python -m venv venv
venv\Scripts\activate.bat
```

**Windows PowerShell**

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

### 3. 기본 의존성 설치

```bash
pip install -r requirements.txt
```

### 4. 프로그램 실행

```bash
python main.py
```

<h2/>

## 지원 플랫폼

| 플랫폼     | 지원 여부 |
| ------- | ----- |
| Windows | O    |
| Linux   | X    |
| macOS   | X    |

<h2/>

## 면책 조항

본 프로그램은 개인 연구 및 학습을 목적으로 제작된 크롤링 도구입니다.

* 본 프로그램은 플랫폼의 콘텐츠를 저장하고 변환 할 수 있는 기능을 제공하지만, 저장되는 콘텐츠의 저작권은 해당 원작자 및 권리자에게 있습니다.
* 프로그램을 이용하여 다운로드하거나 생성한 콘텐츠의 이용에 대한 책임은 사용자에게 있습니다.
* 프로그램의 사용으로 인해 발생할 수 있는 저작권 침해, 서비스 이용 제한, IP 차단, 계정 제한 및 기타 법적·행정적 문제에 대해 개발자는 책임을 지지 않습니다.
* 프로그램의 사용 또는 결과물로 인해 발생하는 직접적·간접적 손해에 대해 개발자는 책임을 지지 않습니다.