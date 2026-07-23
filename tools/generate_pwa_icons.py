"""Generate the committed e& Care PWA icons from local vector markup."""

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "app" / "static" / "icons"
ICON_SPECS = {
    "apple-touch-icon.png": (180, 0.66),
    "icon-192.png": (192, 0.66),
    "icon-512.png": (512, 0.66),
    "icon-maskable-192.png": (192, 0.50),
    "icon-maskable-512.png": (512, 0.50),
}


def icon_svg(size, mark_scale):
    mark_size = round(size * mark_scale)
    font_size = round(mark_size * 0.68)
    letter_spacing = max(2, round(font_size * 0.11))
    glow_radius = round(size * 0.44)
    return f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">
      <defs>
        <linearGradient id="background" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="#f01818"/>
          <stop offset="0.58" stop-color="#e60000"/>
          <stop offset="1" stop-color="#b80000"/>
        </linearGradient>
        <radialGradient id="highlight" cx="0.18" cy="0.08" r="0.9">
          <stop offset="0" stop-color="#ffffff" stop-opacity="0.22"/>
          <stop offset="1" stop-color="#ffffff" stop-opacity="0"/>
        </radialGradient>
        <filter id="shadow" x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="{max(2, round(size * 0.025))}" stdDeviation="{max(2, round(size * 0.025))}" flood-color="#750000" flood-opacity="0.3"/>
        </filter>
      </defs>
      <rect width="{size}" height="{size}" fill="url(#background)"/>
      <circle cx="{round(size * 0.12)}" cy="{round(size * 0.08)}" r="{glow_radius}" fill="url(#highlight)"/>
      <g filter="url(#shadow)">
        <rect x="{(size - mark_size) / 2:.2f}" y="{(size - mark_size) / 2:.2f}" width="{mark_size}" height="{mark_size}" rx="{round(mark_size * 0.26)}" fill="#ffffff" fill-opacity="0.10" stroke="#ffffff" stroke-opacity="0.16" stroke-width="{max(1, round(size * 0.006))}"/>
        <text x="50%" y="51.5%" dominant-baseline="middle" text-anchor="middle" fill="#ffffff" font-family="Arial Rounded MT Bold, Arial, sans-serif" font-size="{font_size}" font-weight="900" letter-spacing="-{letter_spacing}">e&amp;</text>
      </g>
    </svg>
    """


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(device_scale_factor=1)
        for filename, (size, mark_scale) in ICON_SPECS.items():
            page.set_viewport_size({"width": size, "height": size})
            page.set_content(
                f'<style>html,body{{margin:0;width:{size}px;height:{size}px;overflow:hidden}}</style>'
                + icon_svg(size, mark_scale)
            )
            destination = OUTPUT_DIR / filename
            page.locator("svg").screenshot(path=str(destination), animations="disabled")
            print(f"Generated {destination.relative_to(ROOT)} ({size}x{size})")
        browser.close()


if __name__ == "__main__":
    main()
