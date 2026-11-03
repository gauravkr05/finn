"""Builds the test fixtures: a screener.in-like company page and two transcript PDFs.

Numbers are synthetic and exist only to exercise the parser and the judging logic.
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

HERE = Path(__file__).parent

Q_HEAD = ["Sep 2024", "Dec 2024", "Mar 2025", "Jun 2025", "Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026"]
Q_SALES = [1000, 1050, 1100, 1080, 1150, 1210, 1260, 1240, 1300]
Q_OPM = [18, 18.5, 19, 18, 18.2, 18.8, 19.1, 17.6, 17.9]
Q_OP = [round(s * m / 100) for s, m in zip(Q_SALES, Q_OPM)]
Q_NP = [120, 128, 140, 125, 130, 142, 150, 128, 135]

A_HEAD = ["Mar 2021", "Mar 2022", "Mar 2023", "Mar 2024", "Mar 2025", "Mar 2026", "TTM"]
A_SALES = [2800, 3200, 3700, 3950, 4230, 4860, 5010]
A_OP = [450, 540, 650, 720, 790, 910, 925]
A_OPM = [16, 17, 18, 18, 19, 19, 18]
A_NP = [300, 360, 420, 470, 513, 552, 555]


def row(label, vals, button=False):
    lab = f'<button class="button-plain">{label}&nbsp;<span class="blue-icon">+</span></button>' if button else label
    tds = "".join(f'<td class="">{v:,}</td>' if isinstance(v, (int, float)) else f"<td>{v}</td>" for v in vals)
    return f'<tr class="stripe"><td class="text">{lab}</td>{tds}</tr>'


def table(sid, heads, rows):
    th = "".join(f'<th class="">{h}</th>' for h in heads)
    return (f'<section id="{sid}" class="card card-large"><div class="responsive-holder">'
            f'<table class="data-table responsive-text-nowrap"><thead><tr><th class="text"></th>{th}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div></section>')


def company_html():
    pct = lambda xs: [f"{x}%" for x in xs]
    parts = [
        '<html><body><h1 class="h2 shrink-text">Fixture Paints Ltd</h1>',
        '<ul id="top-ratios"><li class="flex"><span class="name">Market Cap</span><span class="nowrap value">₹ <span class="number">45,000</span> Cr.</span></li>'
        '<li class="flex"><span class="name">ROCE</span><span class="nowrap value"><span class="number">24.1</span> %</span></li>'
        '<li class="flex"><span class="name">Stock P/E</span><span class="nowrap value"><span class="number">52.3</span></span></li></ul>',
        table("quarters", Q_HEAD, [row("Sales", Q_SALES, True), row("Operating Profit", Q_OP), row("OPM %", pct(Q_OPM)),
                                   row("Net Profit", Q_NP, True)]),
        table("profit-loss", A_HEAD, [row("Sales", A_SALES, True), row("Operating Profit", A_OP),
                                      row("OPM %", pct(A_OPM)), row("Net Profit", A_NP, True)]),
        table("balance-sheet", A_HEAD[:-1], [row("Equity Capital", [96] * 6), row("Reserves", [1500, 1800, 2100, 2450, 2800, 3200]),
                                             row("Borrowings", [400, 380, 350, 300, 220, 150], True)]),
        table("cash-flow", A_HEAD[:-1], [row("Cash from Operating Activity", [320, 300, 450, 520, 560, 610], True),
                                         row("Cash from Investing Activity", [-200, -250, -300, -280, -260, -300], True)]),
        table("ratios", A_HEAD[:-1], [row("Cash Conversion Cycle", [40, 42, 45, 50, 52, 55]),
                                      row("Working Capital Days", [30, 31, 33, 35, 36, 38])]),
        '<section id="documents"><div class="documents annual-reports flex-column"><h3>Annual reports</h3><ul class="list-links">'
        '<li><a href="https://example.com/ar2026.pdf">Financial Year 2026<div class="ink-600 smaller">from bse</div></a></li>'
        '<li><a href="https://example.com/ar2025.pdf">Financial Year 2025<div>from bse</div></a></li></ul></div>'
        '<div class="documents concalls flex-column"><h3>Concalls</h3><ul class="list-links">',
    ]
    for date, slug in [("Oct 2026", "q2"), ("Jul 2026", "q1"), ("Apr 2026", "q4"), ("Jan 2026", "q3")]:
        parts.append(f'<li class="flex flex-gap-8 flex-wrap"><div class="ink-600 font-size-15 nowrap">{date}</div>'
                     f'<a class="concall-link" href="https://example.com/{slug}.pdf" title="Raw Transcript">Transcript</a>'
                     f'<a class="concall-link" href="https://example.com/{slug}-ppt.pdf" title="PPT">PPT</a></li>')
    parts.append("</ul></div></section></body></html>")
    return "".join(parts)


def transcript_pdf(path, lines_by_page):
    c = canvas.Canvas(str(path), pagesize=A4)
    for lines in lines_by_page:
        c.setFont("Helvetica", 9)
        c.drawString(40, 815, "Fixture Paints Limited  Earnings Conference Call")
        y = 790
        for ln in lines:
            c.drawString(40, y, ln)
            y -= 14
        c.drawString(280, 30, "1")
        c.showPage()
    c.save()


if __name__ == "__main__":
    (HERE / "screener_company.html").write_text(company_html(), encoding="utf-8")
    transcript_pdf(HERE / "transcript_q4fy26.pdf", [
        ["Moderator: Ladies and gentlemen, welcome to the Q4 FY26 earnings conference call.",
         "Rajesh Kumar: Thank you. We are India's second-largest decorative paints company with",
         "a growing industrial coatings business. Decorative paints contribute about 80 percent of revenue."],
        ["Rajesh Kumar: For FY27 we remain confident of 12 to 15 percent revenue growth.",
         "We expect EBITDA margin to stay in the 19 to 21 percent band for the full year.",
         "We will commission the new Dahej plant by the third quarter of FY27.",
         "Moderator: The first question is from the line of Priya Shah."],
    ])
    transcript_pdf(HERE / "transcript_q2fy27.pdf", [
        ["Moderator: Welcome to the Q2 FY27 earnings call.",
         "Rajesh Kumar: Demand was soft this quarter. We now expect 8 to 10 percent revenue growth for FY27.",
         "The Dahej plant was commissioned in September, ahead of schedule.",
         "Raw material prices were stable through the quarter and we took no price increase.",
         "Our dealer network expanded to over 60,000 outlets across the country this year.",
         "Moderator: The first question is from the line of Amit Verma from a domestic fund."],
    ])
    print("fixtures written")
