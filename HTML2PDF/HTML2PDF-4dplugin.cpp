#include "HTML2PDF-4dplugin.h"
#include "pdf_container.h"
#include <string>
#include <fstream>
#include <sstream>

static std::string unistring_to_utf8(PA_Unistring* ustr) {
    if (!ustr) return "";
    const PA_Unichar* buf = PA_GetUnistring(ustr);
    int len = PA_GetUnistringLength(ustr);
    if (!buf || len <= 0) return "";
    
    std::string result;
    result.reserve(len * 3);
    for (int i = 0; i < len; i++) {
        unsigned int c = (unsigned int)buf[i];
        // Handle surrogate pairs
        if (c >= 0xD800 && c <= 0xDBFF && i + 1 < len) {
            unsigned int lo = (unsigned int)buf[i + 1];
            if (lo >= 0xDC00 && lo <= 0xDFFF) {
                c = 0x10000 + ((c - 0xD800) << 10) + (lo - 0xDC00);
                i++;
            }
        }
        if (c < 0x80) {
            result += (char)c;
        } else if (c < 0x800) {
            result += (char)(0xC0 | (c >> 6));
            result += (char)(0x80 | (c & 0x3F));
        } else if (c < 0x10000) {
            result += (char)(0xE0 | (c >> 12));
            result += (char)(0x80 | ((c >> 6) & 0x3F));
            result += (char)(0x80 | (c & 0x3F));
        } else {
            result += (char)(0xF0 | (c >> 18));
            result += (char)(0x80 | ((c >> 12) & 0x3F));
            result += (char)(0x80 | ((c >> 6) & 0x3F));
            result += (char)(0x80 | (c & 0x3F));
        }
    }
    return result;
}

void HTML2PDF_Command(PA_PluginParameters params) {
    PA_Unistring* htmlPathUni = PA_GetStringParameter(params, 1);
    PA_Unistring* pdfPathUni = PA_GetStringParameter(params, 2);
    
    std::string htmlPath = unistring_to_utf8(htmlPathUni);
    std::string pdfPath = unistring_to_utf8(pdfPathUni);
    
    // Read HTML file
    std::ifstream file(htmlPath);
    if (!file.is_open()) {
        PA_ReturnLong(params, 1); // file not found
        return;
    }
    std::stringstream ss;
    ss << file.rdbuf();
    std::string html = ss.str();
    file.close();
    
    if (html.empty()) {
        PA_ReturnLong(params, 2); // empty file
        return;
    }
    
    // Convert
    pdf_container container;
    bool ok = container.render_to_pdf(html, pdfPath);
    
    PA_ReturnLong(params, ok ? 0 : 3);
}

#if defined(__cplusplus)
extern "C" {
#endif

void PluginMain(PA_long32 selector, PA_PluginParameters params) {
    switch (selector) {
        case 1:
            HTML2PDF_Command(params);
            break;
        default:
            break;
    }
}

#if defined(__cplusplus)
}
#endif
