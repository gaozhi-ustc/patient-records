---
name: notebooklm-mdt-extractor
description: Generates a deep-research Prompt for NotebookLM to extract patient MDT clinical records and PPT outlines based on the "刘心宇" standard format. Use when the user asks to process a patient's medical records for NotebookLM.
---
# NotebookLM MDT Extractor Skill

This skill generates a highly structured prompt to be used in Google NotebookLM (with Deep Research enabled). It instructs NotebookLM to process raw patient medical files (PDFs, images, docx) and output a standardized "门诊记录单" (Clinical Record) and a "临床汇报PPT大纲" (PPT Outline) matching the visual and structural quality of the reference patient (刘心宇).

## Usage

When triggered, do the following:

1. Read the `references/prompt_template.md` file.
2. Replace the `[PATIENT_NAME]` placeholder with the target patient's name requested by the user.
3. Output the exact final prompt to the user inside a markdown code block so they can easily copy and paste it into NotebookLM.
4. Instruct the user to:
   - Go to [Google NotebookLM](https://notebooklm.google.com).
   - Create a new notebook and upload the patient's files (e.g., the specific PDF from `patients/pdf/[patient_name].pdf`).
   - Enable "Deep Research" (or equivalent comprehensive extraction/reasoning modes).
   - Paste the provided prompt into the chat box.
