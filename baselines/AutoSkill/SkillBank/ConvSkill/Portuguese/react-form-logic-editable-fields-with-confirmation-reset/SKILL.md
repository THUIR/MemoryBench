---
id: "8c51f410-9a79-4a26-b1d2-5573ae09402c"
name: "React Form Logic: Editable Fields with Confirmation Reset"
description: "Implementa um comportamento de formulário onde os campos permanecem editáveis após o envio, mas editar eles aciona um diálogo de confirmação que reseta o estado do formulário."
version: "0.1.0"
tags:
  - "react"
  - "formulario"
  - "reset"
  - "confirmacao"
  - "javascript"
  - "frontend"
triggers:
  - "alterar logica do formulario"
  - "campos editaveis com popup de reset"
  - "remover disabled dos inputs"
  - "confirmar reset ao editar"
---

# React Form Logic: Editable Fields with Confirmation Reset

Implementa um comportamento de formulário onde os campos permanecem editáveis após o envio, mas editar eles aciona um diálogo de confirmação que reseta o estado do formulário.

## Prompt

Você é um desenvolvedor React. O usuário quer modificar a lógica nos componentes `FormularioAtendimento` e `NovoAtendimento`. Atualmente, os campos são desabilitados após adicionar um procedimento usando `disabled={camposFixos}`. 

**Requisito 1:** Remova o atributo `disabled={camposFixos}` dos inputs (Modalidade, Fonte Pagadora, Paciente, Local, Data, Valores). 

**Requisito 2:** Implemente uma lógica de confirmação. Quando o usuário tentar alterar qualquer um desses inputs, mostre um popup pedindo confirmação. 

**Requisito 3:** A mensagem do popup deve ser: "Isso irá resetar tudo que ja foi feito e ira resetar criando um card novo de procedimento". 

**Requisito 4:** Se o usuário confirmar, resete o estado do formulário (limpar todos os campos). 
**Requisito 5:** Não altere CSS ou estrutura existente do componente, a menos que seja necessário para a lógica. 
**Requisito 6:** Forneça o código completo modificado para os componentes.

## Triggers

- alterar logica do formulario
- campos editaveis com popup de reset
- remover disabled dos inputs
- confirmar reset ao editar
