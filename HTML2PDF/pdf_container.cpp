#include "pdf_container.h"
#include <cstring>
#include <cmath>
#include <algorithm>
#include <cctype>
#include <fstream>
#include <sstream>
#include "stb_image.h"

pdf_container::pdf_container()
    : m_pdf(nullptr), m_current_page(nullptr),
      m_page_width(595.28f), m_page_height(841.89f),
      m_current_page_offset_y(0), m_next_font_id(1) {}

pdf_container::~pdf_container() {
    for (auto& p : m_fonts) delete p.second;
    m_images.clear();
}

std::string pdf_container::map_font_name(const std::string& family, bool bold, bool italic) {
    std::string lower;
    for (char c : family) lower += (char)std::tolower((unsigned char)c);

    std::string base;
    if (lower.find("courier") != std::string::npos || lower.find("monospace") != std::string::npos) {
        base = "Courier";
    } else if (lower.find("times") != std::string::npos || (lower.find("serif") != std::string::npos && lower.find("sans") == std::string::npos)) {
        base = "Times";
    } else {
        base = "Helvetica";
    }

    if (base == "Times") {
        if (bold && italic) return "Times-BoldItalic";
        if (bold) return "Times-Bold";
        if (italic) return "Times-Italic";
        return "Times-Roman";
    } else if (base == "Courier") {
        if (bold && italic) return "Courier-BoldOblique";
        if (bold) return "Courier-Bold";
        if (italic) return "Courier-Oblique";
        return "Courier";
    } else {
        if (bold && italic) return "Helvetica-BoldOblique";
        if (bold) return "Helvetica-Bold";
        if (italic) return "Helvetica-Oblique";
        return "Helvetica";
    }
}

litehtml::uint_ptr pdf_container::create_font(const litehtml::font_description& descr,
    const litehtml::document* doc, litehtml::font_metrics* fm) {

    bool is_bold = descr.weight >= 700;
    bool is_italic = (descr.style == litehtml::font_style_italic);

    auto* fi = new font_info();
    fi->hpdf_font_name = map_font_name(descr.family, is_bold, is_italic);
    fi->size = (int)(float)descr.size;
    if (fi->size <= 0) fi->size = 12;

    if (fm && m_pdf) {
        HPDF_Font font = HPDF_GetFont(m_pdf, fi->hpdf_font_name.c_str(), nullptr);
        if (font) {
            int ascent = HPDF_Font_GetAscent(font);
            int descent = HPDF_Font_GetDescent(font);
            fm->ascent = (int)(ascent * fi->size / 1000.0f);
            fm->descent = (int)(-descent * fi->size / 1000.0f);
            fm->height = fm->ascent + fm->descent;
            fm->x_height = (int)(fm->height * 0.5f);
        } else {
            fm->height = fi->size;
            fm->ascent = (int)(fi->size * 0.8f);
            fm->descent = (int)(fi->size * 0.2f);
            fm->x_height = (int)(fi->size * 0.5f);
        }
        fi->metrics = *fm;
    } else {
        fi->metrics.height = fi->size;
        fi->metrics.ascent = (int)(fi->size * 0.8f);
        fi->metrics.descent = (int)(fi->size * 0.2f);
        fi->metrics.x_height = (int)(fi->size * 0.5f);
    }

    litehtml::uint_ptr id = m_next_font_id++;
    m_fonts[id] = fi;
    return id;
}

void pdf_container::delete_font(litehtml::uint_ptr hFont) {
    auto it = m_fonts.find(hFont);
    if (it != m_fonts.end()) { delete it->second; m_fonts.erase(it); }
}

litehtml::pixel_t pdf_container::text_width(const char* text, litehtml::uint_ptr hFont) {
    auto it = m_fonts.find(hFont);
    if (it == m_fonts.end() || !m_pdf) return 0;
    font_info* fi = it->second;
    HPDF_Font font = HPDF_GetFont(m_pdf, fi->hpdf_font_name.c_str(), nullptr);
    if (!font) return (int)(strlen(text) * fi->size * 0.5f);
    HPDF_TextWidth tw = HPDF_Font_TextWidth(font, (const HPDF_BYTE*)text, (HPDF_UINT)strlen(text));
    return (int)(tw.width * fi->size / 1000.0f);
}

void pdf_container::draw_text(litehtml::uint_ptr hdc, const char* text, litehtml::uint_ptr hFont,
    litehtml::web_color color, const litehtml::position& pos) {
    if (!m_current_page || !text || !*text) return;
    auto it = m_fonts.find(hFont);
    if (it == m_fonts.end()) return;
    font_info* fi = it->second;
    HPDF_Font font = HPDF_GetFont(m_pdf, fi->hpdf_font_name.c_str(), nullptr);
    if (!font) return;

    float pdf_y = m_page_height - ((float)pos.y - m_current_page_offset_y) - fi->metrics.ascent;
    HPDF_Page_SetFontAndSize(m_current_page, font, (HPDF_REAL)fi->size);
    HPDF_Page_SetRGBFill(m_current_page, color.red / 255.0f, color.green / 255.0f, color.blue / 255.0f);
    HPDF_Page_BeginText(m_current_page);
    HPDF_Page_TextOut(m_current_page, (HPDF_REAL)(float)pos.x, pdf_y, text);
    HPDF_Page_EndText(m_current_page);
}

void pdf_container::draw_solid_fill(litehtml::uint_ptr hdc, const litehtml::background_layer& layer, const litehtml::web_color& color) {
    // Disabled — dark-mode CSS often produces unwanted fills since litehtml
    // doesn't execute JS (e.g. data-theme="light" never gets set).
    (void)hdc; (void)layer; (void)color;
}

void pdf_container::draw_borders(litehtml::uint_ptr hdc, const litehtml::borders& borders,
    const litehtml::position& draw_pos, bool root) {
    if (!m_current_page) return;
    auto draw_side = [&](const litehtml::border& b, float x1, float y1, float x2, float y2) {
        if ((int)b.width == 0 || b.style == litehtml::border_style_none || b.style == litehtml::border_style_hidden) return;
        HPDF_Page_SetRGBStroke(m_current_page, b.color.red / 255.0f, b.color.green / 255.0f, b.color.blue / 255.0f);
        HPDF_Page_SetLineWidth(m_current_page, (float)b.width);
        HPDF_Page_MoveTo(m_current_page, x1, y1);
        HPDF_Page_LineTo(m_current_page, x2, y2);
        HPDF_Page_Stroke(m_current_page);
    };
    float left = (float)draw_pos.x;
    float top = m_page_height - ((float)draw_pos.y - m_current_page_offset_y);
    float right = left + (float)draw_pos.width;
    float bottom = top - (float)draw_pos.height;
    draw_side(borders.top, left, top, right, top);
    draw_side(borders.bottom, left, bottom, right, bottom);
    draw_side(borders.left, left, top, left, bottom);
    draw_side(borders.right, right, top, right, bottom);
}

bool pdf_container::render_to_pdf(const std::string& html, const std::string& pdf_path) {
    m_pdf = HPDF_New(nullptr, nullptr);
    if (!m_pdf) return false;

    // Reset cached HPDF_Image handles (they belong to the previous m_pdf)
    for (auto& kv : m_images) kv.second.hpdf_image = nullptr;

    auto doc = litehtml::document::createFromString(html.c_str(), this);
    if (!doc) { HPDF_Free(m_pdf); m_pdf = nullptr; return false; }

    int content_width = (int)m_page_width - 40;
    doc->render(content_width);
    int total_height = (int)doc->height();
    int page_content_height = (int)m_page_height - 40;
    int num_pages = std::max(1, (total_height + page_content_height - 1) / page_content_height);

    for (int page = 0; page < num_pages; page++) {
        m_current_page = HPDF_AddPage(m_pdf);
        HPDF_Page_SetSize(m_current_page, HPDF_PAGE_SIZE_A4, HPDF_PAGE_PORTRAIT);
        m_current_page_offset_y = page * page_content_height;
        litehtml::position clip(0, m_current_page_offset_y, content_width, page_content_height);
        doc->draw((litehtml::uint_ptr)this, 20, 20 - m_current_page_offset_y, &clip);
    }

    HPDF_STATUS status = HPDF_SaveToFile(m_pdf, pdf_path.c_str());
    HPDF_Free(m_pdf);
    m_pdf = nullptr;
    m_current_page = nullptr;
    return status == HPDF_OK;
}

litehtml::pixel_t pdf_container::pt_to_px(float pt) const { return (int)pt; }
litehtml::pixel_t pdf_container::get_default_font_size() const { return 12; }
const char* pdf_container::get_default_font_name() const { return "Helvetica"; }

void pdf_container::draw_list_marker(litehtml::uint_ptr hdc, const litehtml::list_marker& marker) {
    if (!m_current_page) return;
    float x = (float)marker.pos.x + (float)marker.pos.width / 2.0f;
    float y = m_page_height - ((float)marker.pos.y - m_current_page_offset_y) - (float)marker.pos.height / 2.0f;
    HPDF_Page_SetRGBFill(m_current_page, marker.color.red / 255.0f, marker.color.green / 255.0f, marker.color.blue / 255.0f);
    HPDF_Page_Circle(m_current_page, x, y, 2.0f);
    HPDF_Page_Fill(m_current_page);
}

void pdf_container::load_image(const char* src, const char* baseurl, bool) {
    if (!src || !*src) return;
    std::string path = src;
    if (!path.empty() && path[0] != '/') {
        std::string base = (baseurl && *baseurl) ? baseurl : m_base_url;
        if (!base.empty()) path = base + "/" + path;
    }
    if (m_images.count(src)) return;
    int w = 0, h = 0, channels = 0;
    unsigned char* data = stbi_load(path.c_str(), &w, &h, &channels, 3);
    if (!data) return;
    image_info info;
    info.width = w;
    info.height = h;
    info.pixel_data.assign(data, data + w * h * 3);
    info.hpdf_image = nullptr;
    stbi_image_free(data);
    m_images[src] = std::move(info);
}
void pdf_container::get_image_size(const char* src, const char*, litehtml::size& sz) {
    auto it = m_images.find(src ? src : "");
    if (it != m_images.end()) { sz.width = it->second.width; sz.height = it->second.height; }
    else { sz.width = 0; sz.height = 0; }
}
void pdf_container::draw_image(litehtml::uint_ptr, const litehtml::background_layer& layer, const std::string& url, const std::string&) {
    if (!m_current_page || !m_pdf) return;
    auto it = m_images.find(url);
    if (it == m_images.end()) return;
    auto& img = it->second;
    if (!img.hpdf_image) {
        img.hpdf_image = HPDF_LoadRawImageFromMem(m_pdf, img.pixel_data.data(),
            img.width, img.height, HPDF_CS_DEVICE_RGB, 8);
        if (!img.hpdf_image) return;
    }
    float x = (float)layer.border_box.x;
    float w = (float)layer.border_box.width;
    float h = (float)layer.border_box.height;
    float y_top = (float)(layer.border_box.y - m_current_page_offset_y);
    float y = m_page_height - y_top - h;
    HPDF_Page_DrawImage(m_current_page, img.hpdf_image, x, y, w, h);
}
void pdf_container::draw_linear_gradient(litehtml::uint_ptr, const litehtml::background_layer&, const litehtml::background_layer::linear_gradient&) {}
void pdf_container::draw_radial_gradient(litehtml::uint_ptr, const litehtml::background_layer&, const litehtml::background_layer::radial_gradient&) {}
void pdf_container::draw_conic_gradient(litehtml::uint_ptr, const litehtml::background_layer&, const litehtml::background_layer::conic_gradient&) {}
void pdf_container::set_caption(const char*) {}
void pdf_container::set_base_url(const char* base_url) {
    if (base_url) m_base_url = base_url;
}
void pdf_container::link(const std::shared_ptr<litehtml::document>& doc, const litehtml::element::ptr& el) {
    if (!doc || !el) return;
    const char* rel = el->get_attr("rel");
    const char* href = el->get_attr("href");
    if (!rel || !href) return;
    std::string rel_str(rel);
    if (rel_str != "stylesheet") return;
    
    std::string path(href);
    if (!path.empty() && path[0] != '/' && !m_base_url.empty()) {
        path = m_base_url + "/" + path;
    }
    std::ifstream f(path);
    if (f.is_open()) {
        std::stringstream ss;
        ss << f.rdbuf();
        std::string css = ss.str();
        if (!css.empty()) {
            doc->add_stylesheet(css.c_str(), href, nullptr);
        }
    }
}
void pdf_container::on_anchor_click(const char*, const litehtml::element::ptr&) {}
void pdf_container::on_mouse_event(const litehtml::element::ptr&, litehtml::mouse_event) {}
void pdf_container::set_cursor(const char*) {}
void pdf_container::transform_text(std::string& text, litehtml::text_transform tt) {
    if (tt == litehtml::text_transform_uppercase) std::transform(text.begin(), text.end(), text.begin(), ::toupper);
    else if (tt == litehtml::text_transform_lowercase) std::transform(text.begin(), text.end(), text.begin(), ::tolower);
}
void pdf_container::import_css(std::string& text, const std::string& url, std::string& baseurl) {
    text.clear();
    std::string path = url;
    // Resolve relative to base URL (directory)
    if (!path.empty() && path[0] != '/' && !m_base_url.empty()) {
        path = m_base_url + "/" + path;
    }
    std::ifstream f(path);
    if (f.is_open()) {
        std::stringstream ss;
        ss << f.rdbuf();
        text = ss.str();
        // Set baseurl for nested @import
        auto pos = path.rfind('/');
        if (pos != std::string::npos) baseurl = path.substr(0, pos);
    }
}
void pdf_container::set_clip(const litehtml::position&, const litehtml::border_radiuses&) {}
void pdf_container::del_clip() {}
void pdf_container::get_viewport(litehtml::position& vp) const {
    vp.x = 0; vp.y = 0;
    vp.width = (int)m_page_width - 40;
    vp.height = (int)m_page_height - 40;
}
litehtml::element::ptr pdf_container::create_element(const char*, const litehtml::string_map&,
    const std::shared_ptr<litehtml::document>&) { return nullptr; }
void pdf_container::get_media_features(litehtml::media_features& media) const {
    media.type = litehtml::media_type_print;
    media.width = (int)m_page_width;
    media.height = (int)m_page_height;
    media.device_width = (int)m_page_width;
    media.device_height = (int)m_page_height;
    media.color = 8;
    media.monochrome = 0;
    media.color_index = 256;
    media.resolution = 96;
}
void pdf_container::get_language(std::string& language, std::string& culture) const {
    language = "en"; culture = "";
}
