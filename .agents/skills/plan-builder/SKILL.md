---
name: plan-builder
description: >
  Generate structured implementation plans from conversation context.
  Use when someone asks to "create a plan," "break this into steps,"
  or wraps up exploration and wants to move to building. Transforms
  discussion into a trackable execution document without writing code.
---

# Plan Builder

You are transitioning from thinking mode to building mode. Your job
is to produce a single, high-signal implementation plan that a
developer can execute step-by-step without needing to re-read the
conversation.

This is a planning document, not a coding session. Do not write code.

## Before you write anything

Scan the full conversation for:
1. The goal — what should exist when this is done
2. Decisions already made — constraints, tradeoffs discussed
3. Open questions — anything ambiguous or unresolved
4. Scope boundaries — what's in, what's out

If open questions remain, surface them BEFORE producing the plan.

## Plan structure

Use this template:

# Implementation Plan: [Title]

**Progress:** 0% · **Status:** Not started

## TLDR
[2-3 sentences. What, for whom, key technical approach.]

## Scope
**In scope:** [list]
**Out of scope:** [list with reasons]

## Tasks

- [ ] **1. [Task name]** · _[S/M/L]_
  [What this accomplishes and why it comes here.]
  - [ ] 1.1 [Concrete, verifiable subtask]
  - [ ] 1.2 [Subtask]

## Verification
[2-4 concrete checks to confirm completion.]

## How to write good tasks

- Ordered by dependency
- One concern per task
- Subtasks are actions, not descriptions
- Verifiable completion
- No gold-plating

## What NOT to do

- Don't include code snippets in the plan.
- Don't add testing/docs tasks unless asked.
- Don't hedge. If uncertain, put it in Assumptions.
