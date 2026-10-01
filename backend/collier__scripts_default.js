// --- Utility Function: Set rbottom visibility ---
function setRbottomVisibility(state) {
    try {
        var rbottom = window.parent && window.parent.document.getElementById('rbottom');
        if (rbottom) {
            rbottom.style.visibility = (state === 'on') ? 'visible' : 'hidden';
        }
    } catch (e) {
        // Ignore cross-origin or missing frame errors
    }
}

// Turn rbottom off at the very start
setRbottomVisibility('off');

// --- Main jQuery startup ---
$(function () {
    var path = window.location.pathname.toLowerCase();

    if (path.includes("/main_search/")) {
        // Replace current history state so nothing from /main_search/ adds to it
        history.replaceState(null, '', window.location.href);

        // Intercept forward navigation inside main_search to avoid new history entries
        $(document).on('click', 'a', function (e) {
            var href = $(this).attr('href');
            if (href && href.toLowerCase().includes("/main_search/") && !href.startsWith("javascript:")) {
                e.preventDefault();
                window.location.replace(href);
            }
        });
    }
});

// --- Document Ready Handler ---
$(document).ready(function () {

    $(function () {
        try {
            $(".btn").button();
        } catch (err) {}
    });

    initAccordions();

    if ($("form").length == 1) {
        $("<input type='hidden' value='' />")
            .attr("id", "WInnerWidth")
            .attr("name", "WInnerWidth")
            .appendTo("form")
            .val(window.innerWidth);

        $("<input type='hidden' value='' />")
            .attr("id", "WInnerHeight")
            .attr("name", "WInnerHeight")
            .appendTo("form")
            .val(window.innerHeight);
    }

    try {
        if (window.frameElement && window.frameElement.id === 'rbottom') {

           // --- Scroll control for rbottom ---
            const path = window.location.pathname.toLowerCase();
            const file = path.substring(path.lastIndexOf("/") + 1);

            // pages that should have no scrollbars
            const noScrollPages = ["accountdetail.html", "parceldetail.html"];

            if (noScrollPages.includes(file)) {
                window.frameElement.scrolling = "no";
                document.body.style.overflow = "hidden";
            } else {
                window.frameElement.scrolling = "auto";
                document.body.style.overflow = "auto";
            }

            // Note: originally deferred with window.setTimeout(addfooter, 0);
            // Keeping direct call for now; restore timeout if layout issues appear.
            addfooter();
            addPrintButton();
        } else {
            setRbottomVisibility('on');
        }
    } catch (e) { }
});

function addPrintButton(force) {
    const path = window.location.pathname.toLowerCase();
    if (path.includes("/main_search/") && !path.includes("taxestimator.html")) return;
    if (path.includes("/main_maps/")) return;
    if (!(window.frameElement && window.frameElement.name === 'rbottom') && (!force)) return;

    const $btn = $('<a id="btnPrint" class="btn toolbarsm no-print" href="#">Print</a>').css({
        position: 'absolute',
        top: '8px',
        left: '5px',

        zIndex: 9999
    }).on('click', function (e) {
        e.preventDefault();

        if ($('.accordion').length > 0) {
            smartPrintAccordion();
        } else {
            window.print();
        }
    });

    $('body').prepend($btn);

    // if tblHeader exists, bump the Print button over by 80px
    if ($('#tblHeader').length) {
        $('#tblHeader').css('padding-left', '80px');
    }

}

function smartPrintAccordion() {
    const $accordion = $('.accordion');
    const headers = $accordion.find('h3');

    // If no accordion or no headers, just print
    if ($accordion.length === 0 || headers.length === 0) {
        window.print();
        return;
    }

    const totalHeaders = headers.length;
    const collapsed = headers.filter('.ui-accordion-header-collapsed');
    const collapsedCount = collapsed.length;

    // Capture current open sections
    const openIndexes = [];
    $accordion.each(function (i, acc) {
        $(acc).find('h3').each(function (idx, h) {
            if ($(h).hasClass('ui-state-active')) {
                openIndexes.push({ acc, idx });
            }
        });
    });

    // Case 1: All sections open
    if (collapsedCount === 0 && totalHeaders > 0) {
        window.print();
        return;
    }

    // Case 2: All sections closed
    if (openIndexes.length === 0 && totalHeaders > 0) {
        collapsed.click();
        setTimeout(() => {
            window.print();
            setTimeout(() => {
                $('.accordion').accordion("option", "active", false);
            }, 500);
        }, 500);
        return;
    }

    // Case 3: Partially open — show dialog
    showPrintDialog(openIndexes, collapsed);
}

function showPrintDialog(openIndexes, collapsed) {
    $('<div title="Print Options" class="no-print">')
        .append('<p>Would you like to print the entire page (expand all sections) or just the visible content?</p>')
        .dialog({
            modal: true,
            width: 500,
            position: {
                my: "center top+50",
                at: "center top+50",
                of: window,
            },
            buttons: {
                "Print Entire Page": function () {
                    collapsed.click();
                    $(this).dialog('close');
                    setTimeout(() => {
                        window.print();
                        setTimeout(() => {
                            $('.accordion').accordion("option", "active", false);
                            openIndexes.forEach(({ acc, idx }) => {
                                $(acc).accordion("option", "active", idx);
                            });
                        }, 500);
                    }, 500);
                },
                "Print Visible Only": function () {
                    $(this).dialog('close');
                    window.print();
                },
                Cancel: function () {
                    $(this).dialog('close');
                }
            },
            close: function () {
                $(this).remove();
            }
        });
}

// --- Function Definitions ---
function addfooter() {
    const focused = document.activeElement;

    $('html, body').css({
        'overflow-x': 'hidden'
    });

    $('#pagefooter').remove();

    $('body').append(
        '<div id="pagefooter" class="pagefooter no-print" style="width:100%; max-width:100%; overflow:hidden; box-sizing:border-box;"></div>'
    );

    $('#pagefooter').load('/footer.htm?version=' + AppVersion, function () {
        if (focused && typeof focused.focus === 'function') {
            focused.focus();
        }
    });

    setRbottomVisibility('on');
}

function expiresOn() {
    var d = new Date();
    var year = d.getFullYear();
    var month = d.getMonth();
    var day = d.getDate();
    var hour = 6;
    var min = 0;

    var expire = new Date(year, month, day, hour, min);
    if (d.getTime() >= expire.getTime()) {
        expire.setDate(expire.getDate() + 1);
    }

    year = expire.getFullYear();
    month = expire.getMonth() + 1;
    day = expire.getDate();

    return (
        year +
        (month < 10 ? "0" : "") + month +
        (day < 10 ? "0" : "") + day +
        (hour < 10 ? "0" : "") + hour +
        (min < 10 ? "0" : "") + min
    );
}

function initAccordions() {
    if (!$('#accordion').length) return;

    var sectionCount = $('#accordion > h3').length;
    if (sectionCount <= 1) return;

    var $accordion = $('#accordion');
    var children = $accordion.children();
    for (var i = 0; i < children.length; i++) {
        if (children[i].tagName === 'H3') {
            var $h3 = $(children[i]);
            var $contentDiv = $h3.next('div');
            var $wrapper = $('<div class="accordion"></div>');
            $h3.add($contentDiv).wrapAll($wrapper);
        }
    }

    $(".accordion").accordion({
        collapsible: true,
        active: false,
        heightStyle: "content"
    });

    var $infoBar = $(
        `<div id="accordionInstructionscontainer" class="no-print" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
            <p id="accordionInstructions" style="font-style: italic; margin: 0;">Expand a section below to view details.</p>
            <div style="display: flex; gap: 8px;">
                <button id="expandAll" class="btn toolbar">Expand All</button>
                <button id="collapseAll" class="btn toolbar">Collapse All</button>
            </div>
        </div>`
    );
    $infoBar.insertBefore('#accordion');

    $('#expandAll').on('click', function () {
        $('.accordion h3.ui-accordion-header-collapsed').click();
    });
    $('#collapseAll').on('click', function () {
        $('.accordion h3.ui-state-active').click();
    });
}

function RedirectURL(url) {
    var a = document.createElement("a");
    if (a.click) {
        a.setAttribute("href", url);
        a.style.display = "none";
        document.body.appendChild(a);
        a.click();
    } else {
        window.location.href = url;
    }
}

function removeParameter(qs, parameter) {
    var fullQString = qs.substring(1);
    var paramCount = 0;
    var queryStringComplete = "?";

    if (fullQString.length > 0) {
        var paramArray = fullQString.split("&");

        for (var i = 0; i < paramArray.length; i++) {
            var currentParameter = paramArray[i].split("=");
            if (currentParameter[0] !== parameter) {
                if (paramCount > 0) queryStringComplete += "&";
                queryStringComplete += paramArray[i];
                paramCount++;
            }
        }
    }

    return queryStringComplete;
}

// --- jQuery Extension ---
$.strPad = function (i, l, s) {
    var o = i.toString();
    s = s || '0';
    while (o.length < l) {
        o = s + o;
    }
    return o;
};

// --- jQuery Browser Support ---
jQuery.uaMatch = function (ua) {
    ua = ua.toLowerCase();
    var match =
        /(chrome)[ \/]([\w.]+)/.exec(ua) ||
        /(webkit)[ \/]([\w.]+)/.exec(ua) ||
        /(opera)(?:.*version|)[ \/]([\w.]+)/.exec(ua) ||
        /(msie) ([\w.]+)/.exec(ua) ||
        (ua.indexOf("compatible") < 0 && /(mozilla)(?:.*? rv:([\w.]+)|)/.exec(ua)) || [];
    return {
        browser: match[1] || "",
        version: match[2] || "0"
    };
};

if (!jQuery.browser) {
    var matched = jQuery.uaMatch(navigator.userAgent);
    var browser = {};
    if (matched.browser) {
        browser[matched.browser] = true;
        browser.version = matched.version;
    }
    if (browser.chrome) {
        browser.webkit = true;
    } else if (browser.webkit) {
        browser.safari = true;
    }
    jQuery.browser = browser;
}

// --- Browser Detection ---
var userAgent = navigator.userAgent.toLowerCase();
$.browser.chrome = /chrome/.test(userAgent);

if ($.browser.chrome) {
    userAgent = userAgent.substring(userAgent.indexOf("chrome/") + 7);
    userAgent = userAgent.substring(0, userAgent.indexOf("."));
    $.browser.version = userAgent;
    $.browser.safari = false;
}

if ($.browser.safari) {
    userAgent = userAgent.substring(userAgent.indexOf("safari/") + 7);
    userAgent = userAgent.substring(0, userAgent.indexOf("."));
    $.browser.version = userAgent;
}

var isIE11 = !!navigator.userAgent.match(/Trident.*rv\:11\./);
var isMIE = $.browser.msie && $.browser.version < 10;
var isEdge = window.navigator.userAgent.indexOf("Edge") > -1;

var varPrintMode = 'iframe';
if ($.browser.opera || isMIE || isIE11) {
    varPrintMode = 'popup';
}
if (isEdge) {
    varPrintMode = 'iframe';
}

function goBack() {
    if (document.referrer && document.referrer !== location.href) {
        window.location.href = document.referrer;
    } else {
        window.location.href = "index.html";
    }
}
//window.addEventListener("popstate", function (event) {
//    alert("User is navigating back to: " + document.referrer);
//});

function checkIfPageUp(url, needle, onUp, onDown) {
    $.ajax({
        url: url,
        cache: false,
        timeout: 1000, // 1 second timeout (1000 ms)
        success: function (response) {
            if (typeof response === "string" && response.toLowerCase().indexOf(needle.toLowerCase()) !== -1) {
                onUp();
            } else {
                onDown();
            }
        },
        error: function () {
            onDown();
        }
    });
}

function checkMapAndLoad(mapquerystring) {
    mapquerystring = mapquerystring ? "?" + mapquerystring : "";
    checkIfPageUp(
        "https://" + mapserver + ".collierappraiser.com/up.html",
        "map pool is up",
        // SUCCESS: Page is up, load the MAIN MAP page
        function () {
            var url = "https://" + mapserver + ".collierappraiser.com/map.aspx" + mapquerystring
            window.top.location.replace(url);
        },
        // ERROR: Page is down or not responding, load the MAINTENANCE page
        function () {
            top.frames["rbottom"].location.replace("/Main_Maps/MapMaint.html");

        }
    );
}