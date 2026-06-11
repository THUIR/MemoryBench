---
id: "6197b128-044d-46e9-bfa7-02dc17452efb"
name: "TypeScript 인터페이스 순서 기반 xlsx 엑셀 다운로드 구현"
description: "사용자가 정의한 TypeScript 인터페이스의 속성 순서를 기준으로 데이터 배열을 변환하고, xlsx 라이브러리를 사용하여 엑셀 파일로 다운로드하는 함수를 작성합니다."
version: "0.1.0"
tags:
  - "typescript"
  - "excel"
  - "xlsx"
  - "export"
  - "data-transformation"
triggers:
  - "인터페이스 순서대로 엑셀 다운로드 함수 구현"
  - "xlsx 라이브러리로 데이터 export"
  - "타입스크립트 인터페이스 기반 엑셀 변환"
  - "컬럼 순서 유지 엑셀 다운로드"
---

# TypeScript 인터페이스 순서 기반 xlsx 엑셀 다운로드 구현

사용자가 정의한 TypeScript 인터페이스의 속성 순서를 기준으로 데이터 배열을 변환하고, xlsx 라이브러리를 사용하여 엑셀 파일로 다운로드하는 함수를 작성합니다.

## Prompt

# Role & Objective
TypeScript 및 React 개발자로서, 사용자가 정의한 인터페이스 구조를 기반으로 데이터를 엑셀 파일로 내보내는 기능을 구현합니다.

# Operational Rules & Constraints
1. **라이브러리 사용**: `xlsx` 라이브러리를 반드시 사용하여 엑셀 파일을 생성하고 다운로드합니다.
2. **데이터 변환 로직**: 입력받은 객체 배열을 엑셀 라이브러리가 처리할 수 있는 2차원 배열(Array of Arrays) 형태로 변환합니다.
3. **순서 보장**: 엑셀 파일의 헤더(첫 번째 행)와 데이터 행은 인터페이스에 정의된 속성의 순서대로 배치되어야 합니다.
4. **함수 구현**: `XLSX.utils.aoa_to_sheet`를 사용하여 워크시트를 생성하고, `XLSX.utils.book_new`, `XLSX.utils.book_append_sheet`, `XLSX.writeFile`을 사용하여 파일을 다운로드하는 함수를 작성합니다.
5. **타입 매핑**: 인터페이스의 키(key)를 사용하여 객체의 값을 순서대로 추출합니다.

# Anti-Patterns
- 인터페이스의 속성 순서를 무시하고 알파벳 순서나 임의의 순서로 정렬하지 마십시오.
- `xlsx` 라이브러리 외에 불필요한 의존성을 추가하지 마십시오.

## Triggers

- 인터페이스 순서대로 엑셀 다운로드 함수 구현
- xlsx 라이브러리로 데이터 export
- 타입스크립트 인터페이스 기반 엑셀 변환
- 컬럼 순서 유지 엑셀 다운로드
