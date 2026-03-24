from fpdf import FPDF
import os

def text_to_pdf(text_file, pdf_file):
    if not os.path.exists(text_file):
        print(f"Error: {text_file} not found.")
        return

    with open(text_file, "r", encoding="utf-8") as f:
        text = f.read()

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    
    # Simple multi_cell to handle wrapping
    pdf.multi_cell(0, 10, text)
    
    pdf.output(pdf_file)
    print(f"Converted {text_file} to {pdf_file}")

if __name__ == "__main__":
    files_to_convert = [
        ("mock_quarterly_report_2026.txt", "mock_quarterly_report_2026.pdf"),
        ("mock_risk_strategy_2026.txt", "mock_risk_strategy_2026.pdf")
    ]
    
    for txt, pdf in files_to_convert:
        text_to_pdf(txt, pdf)
