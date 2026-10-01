(function(selfservice) {
	/**
	 * The compatibility mode flag is used to select less modern approaches to
	 * doing certain operations (mostly things that IE 7-9 have trouble with)
	 */
	selfservice.compatibilityMode = false;
    $( document ).on( "mobileinit", function() {

    	$.extend( $.mobile, {
    		defaultPageTransition: 'none'
    	});

    	if(!Modernizr.history) {
    		// If the browser doesn't support pushStep we need to switch back to a
    		// more traditional link handling.
    		$.mobile.ajaxEnabled = false;
    		$.mobile.linkBindingEnabled = false;

    		selfservice.compatibilityMode = true;
    	}
 	});

	/**
	 * Global ajax loading indicator. To avoid showing this you will need to
	 * specify that an ajax request will not generate global events explicitly
	 */
	var toggleLoading = function(startLoading) {
		try {
			if(startLoading) {
				$.mobile.loading("show");
			} else{
				$.mobile.loading("hide");
			}
		} catch(ex) {
			// Ignore this... we don't care
		}
	};
    $(document)
    	.ajaxStart(function(){toggleLoading(true);})
    	.ajaxStop(function(){toggleLoading(false);});


    /**
     * As of JQM 1.4.X the first page loaded is always dom cached. This can lead to
     * issues with pages that have dynamic content not being up to date. We need to
     * remove all pages that should not be cached.
     *
     * Note: This takes advantage of the fact that the pagecontainerhide event is not
     * called when a page is initially shown. If this changes in a future of JQM we might
     * have to make a change here.
     */
    $(document).on("pagecontainerhide", function(event, ui) {
    	var pages = $('div[data-role="page"]');
    	if(pages.length > 1) {
    		pages.filter('*[data-dom-cache="false"]')
    			.not('*[data-external-page="true"]')
    			.remove();
    	}
	});

    /**
     * Perform any jQuery (not jQueryMobile setup)
     */
    $( document ).ready(function() {
    	// Disable caching in ajax requests to avoid some issues in IE
    	$.ajaxSetup({ cache: false });
    });

    /**
     * System-wide change to prevent the back key from performing browser navigation. We ignore backspace in anything that
     * is not a text input field. IE will navigate back if you are on readonly fields, radio buttons, checkboxes, etc.
     * There are lots of fields that allow text input (text, date, number, etc.) so it is easier to check for types we know
     * do not allow input.
     */
    $(document).keydown(function(e){
    	var input = e.target;
        var typeName = input.type; //typeName should end up being things like 'text', 'textarea', 'radio', 'undefined' etc.
        var nodeName = input.nodeName.toLowerCase();
        var readonly = $(e.target).prop("readonly") != "";

        // Back button is key code 8.
        if(e.keyCode == 8 && (readonly || nodeName != "input" || typeName == "radio" || typeName == "checkbox" || typeName == "undefined")) {
            e.preventDefault();
        }
    });

    /**
     * Safely unescape any HTML values in the given text. For example "A &amp; A" becomes "A & A".
     * Use with caution, although this is not supposed to execute any Javascript in the input text.
     */
    selfservice.unescapeHTML = function(text) {
    	if (!text) {
    		return text;
    	}
		var doc = new DOMParser().parseFromString(text, "text/html");
		var unescapedText = text;
		if (doc) {
			unescapedText = doc.documentElement.textContent;
		}
		return unescapedText;
    };

    /**
     * Scroll the screen depending on where the location of the element in focus is relative to the headers and footers.
     * If the focused element is being partially or fully hidden behind either the header or footer, we need to scroll the screen so the user
     * can see the element.
	 */
	selfservice.maybeScrollScreen = function(e) {
    	setTimeout(function() {
	        if (e.keyCode == 9) {
	        	var headerLocation = $("#ss-header-box")[0].getBoundingClientRect();
	        	var footerLocation = $("#ss-footer-box")[0].getBoundingClientRect();
	        	var focusedElementLocation = document.activeElement.getBoundingClientRect();

	        	var headerAndElementBottomDifference = Math.abs(headerLocation.bottom - focusedElementLocation.bottom);
	        	var headerAndElementHeightDifference = headerLocation.height - focusedElementLocation.height;

	        	var footerAndElementTopDifference = Math.abs(footerLocation.top - focusedElementLocation.top);
	        	var footerAndElementHeightDifference = footerLocation.height - focusedElementLocation.height;

	        	if (focusedElementLocation.bottom < headerLocation.bottom ||
	        			headerAndElementBottomDifference < headerAndElementHeightDifference) {
	        		window.scrollTo(0, window.pageYOffset - headerAndElementBottomDifference - headerAndElementHeightDifference);
	        	} else if (footerLocation.top < focusedElementLocation.top ||
	        			footerAndElementTopDifference < footerAndElementHeightDifference) {
        			window.scrollTo(0, window.pageYOffset + footerAndElementTopDifference + footerAndElementHeightDifference);
	        	}
	        }
    	}, 10);
	};

    /**
     * Show a system error to the client.
     */
    selfservice.showError = function(error) {
    	// TODO: stub... fill this in...
    };

    /**
     * Redirects to another page. This should be used in *almost every* case that the page
     * needs to be changed via Javascript to avoid issues with URL rewriting and caching in
     * older versions of IE. You should use this as a drop in replacement for:
     *
     * $.mobile.changePage
     *
     * -or-
     *
     * $(":mobile-pagecontainer").pagecontainer("change", url)
     */
    selfservice.redirect = function(url, reload) {
    	reload = !!reload; // I believe this exists to ensure this value is boolean.
    	if(!selfservice.compatibilityMode) {
    		$(":mobile-pagecontainer").on("pagecontainershow", function( event, ui ) {
    	      // This helps us focus the first field on wizard steps.
    		  $('form:first *:input[type!=hidden]:not([readonly="readonly"]):not([disabled="disabled"]):first').focus();
    		});
    		$(":mobile-pagecontainer").pagecontainer("change", url, {"reload":reload});
    	} else {
    		// In compatibility mode we need to fall back to the less fancy/AJAXless brute force approach
    		if(document && document.location && document.location.href) {
    			document.location.href = url;
    		} else {
    			window.location = url;
    		}
    	}
    };

    /**
     * Redirects to another page using selfservice.redirect, then opens a popup with a message
     *
     */
    selfservice.redirectWithPopup = function(url, reload, message) {
        selfservice.redirect(url, reload);

        setTimeout(function() {
            selfservice.activation.emailContainer.html(message);
            selfservice.activation.popup.popup('open');
        }, 2000);
    };

    /////////////////////////
    // URL Checking
    /////////////////////////
    // initialize objects
    selfservice.url = {};

    // initialize variables
    selfservice.url.homePage;

    // declare methods
    selfservice.url.isHomePage;

    /**
     * Checks to see whether or not the current page is the home page.
     *
     */
    selfservice.url.isHomePage = function(currentUrl) {
    	if (selfservice.url.homePage != undefined && selfservice.url.homePage == currentUrl) {
    		return true;
    	}

    	return false;
    };
    /////////////////////////
    // end URL Checking
    /////////////////////////


    /////////////////////////
    // Account activation
    /////////////////////////
    // initialize objects
    selfservice.activation = {};

    // declare variables
    selfservice.activation.emailContainer;
    selfservice.activation.popup;

    /////////////////////////
    // end Account activation
    /////////////////////////

    /**
     * Set the min height of an element so that its bottom lines up with the bottom of the items identified by the matchSelector.
     * This is used by the Home and Action screens to set the instructions element to be at least as tall as the action items.
     */
    selfservice.setMinHeightToFull = function(div, matchSelector) {
    	if ($(div).position()) {
    		var maxHeight = $(div).height();
    		var left = $(div).position().left;
    		var heightSet=false;

    		$(matchSelector).each(function() {
    			var offset = $(this).position();
    			var height = $(this).outerHeight();

    			var bottom = offset.top + height;

    			// Offset changes to 89 when responsive CSS kicks in (icon width 76 + padding)
    			if (offset.left > 100 && bottom > maxHeight) {
    				maxHeight = bottom;
    				heightSet=true;
    			}
    		});

    		if (!heightSet) {
    			$(div).css("min-height", "");
    		} else {
    			var minHeight = Math.floor(maxHeight - $(div).position().top);
    			var padding = $(div).outerHeight(true) - $(div).innerHeight();
    			minHeight -= (padding/2);

    			$(div).css("min-height", minHeight+"px");
    		}
    		$(div).trigger('create');
    	}
    };
    /////////////////////////
    // Self Service Mode
    /////////////////////////
    // initialize objects
    selfservice.mode = {};

    // declare variables
    selfservice.mode.kioskMode;
    /////////////////////////
    // end Self Service Mode
    /////////////////////////

    /////////////////////////
    // Session Timeout
    /////////////////////////
    // initialize objects
    selfservice.countdown = {};
    selfservice.pages = {};
    selfservice.session = {};
    selfservice.setting = {};

    // declare variables
    selfservice.countdown.continueButton;
    selfservice.countdown.duration = 60; // 60 second default for the count down in the time-out popup
    selfservice.countdown.element;
    selfservice.countdown.handle;
    selfservice.countdown.logoutButton;
    selfservice.countdown.startTime; // start date-time of the count down
    selfservice.countdown.timer;
    selfservice.countdown.timeRemaining;
    selfservice.pages.home;
    selfservice.pages.logout;
    selfservice.pages.ping;
    selfservice.pages.disclaimer;
    selfservice.session.checkInterval = 10 * 1000; // 10 seconds between session checks
    selfservice.session.logoutError;
    selfservice.session.timeout;
    selfservice.session.timeoutElement;
    selfservice.session.timeRemaining;
    selfservice.session.userLoggedIn;
    selfservice.fraudGuard = {};
    selfservice.fraudGuard.finished;

    selfservice.setting.showDisclaimer;
    var oneSecond = 1000;

    // declare methods
    selfservice.countdown.endCount;
    selfservice.countdown.openPopup;
    selfservice.countdown.startCount;
    selfservice.countdown.timer;
    selfservice.session.continueSession;
    selfservice.session.shouldSessionRunForever;
    selfservice.session.keepAlive;
    selfservice.session.logout;

    // method definitions
    /**
     * End the count down so that we don't leave extra count down threads dangling.
     *
     */
    selfservice.countdown.endCount = function () {
        if (typeof selfservice.countdown.handle != 'undefined') {
            clearInterval(selfservice.countdown.handle);
        }
    };

    /**
     * Make sure the count down popup is defined, then open it and begin the count down.
     *
     */
    selfservice.countdown.openPopup = function () {
        if (typeof(selfservice.session.timeoutElement) == 'undefined') {
            selfservice.session.timeoutElement = $("#${selfService.idPrefix}sessionTimeout-popup");
        }
        if (typeof(selfservice.session.timeoutElement) != 'undefined') {
            selfservice.session.timeoutElement.popup().popup('open');
            selfservice.countdown.startCount();
        }
        return false;
    };

    /**
     * Begin the count down inside of the popup to let the user know when the session will expire.
     *
     */
    selfservice.countdown.startCount = function () {
        // Make sure to end any current count downs before beginning a new one.
        selfservice.countdown.endCount();
        selfservice.countdown.startTime = Date.now();
        selfservice.countdown.element = $("#remainingTime");

        // we don't want to wait a full second before the timer starts
        selfservice.countdown.update();
        selfservice.countdown.handle = setInterval(selfservice.countdown.update, oneSecond);
    };

    /**
     * Update the count down display in the popup to reflect the remaining session time.
     *
     */
    selfservice.countdown.update = function () {
        var minutesLeft;
        var secondsLeft;
        // get the number of seconds that have elapsed since startCountDown() was called
        selfservice.countdown.timeRemaining = selfservice.countdown.duration - (((Date.now() - selfservice.countdown.startTime) / oneSecond) | 0);

        // does the same job as parseInt truncates the float
        minutesLeft = (selfservice.countdown.timeRemaining / 60) | 0;
        secondsLeft = (selfservice.countdown.timeRemaining % 60) | 0;

        minutesLeft = minutesLeft < 10 ? "0" + minutesLeft : minutesLeft;
        secondsLeft = secondsLeft < 10 ? "0" + secondsLeft : secondsLeft;

        selfservice.countdown.element.text(minutesLeft + ":" + secondsLeft);

        if (selfservice.countdown.timeRemaining <= 0) {
            // add one second so that the count down starts at the full duration
            // example 05:00 not 04:59
            selfservice.countdown.startTime = Date.now() + oneSecond;

            if (selfservice.session.timeout != null) {
                selfservice.session.logout();
                setTimeout(function() {
                    selfservice.info.addMessage(selfservice.info.message);
                }, 2000);
            }
        }
    };

    /**
     * Make a synchronous call to the server check session page to determine if it
     * is still a valid session that has not timed out.
     */
    selfservice.session.keepAlive = function () {
      if (selfservice.session.shouldSessionRunForever()) {
          selfservice.session.continueSession();
      } else {
        selfservice.countdown.endCount();
        $.ajax({
          type: 'POST',
          url: selfservice.pages.check,
          dataType: 'json',
          data: null,
          global: false,
          success: function(response) {
            if (response > 0) {
              // Continue session
              if (response <= 60) {
                // If we want to run the session to run indefinitely, continue the session
                if (selfservice.session.shouldSessionRunForever()) {
                  selfservice.session.continueSession();
                } else {
                  // Show dialog
                  selfservice.countdown.duration = response;
                  selfservice.countdown.openPopup();
                }
              } else {
                // If the session is continued in 1 tab, the popup needs to be closed in all tabs
                if (typeof(selfservice.session.timeoutElement) != 'undefined') {
                  if (selfservice.session.timeoutElement.hasClass('ui-popup')) {
                    selfservice.session.timeoutElement.popup('close');
                  }
                }
              }
              // reschedule the timer
              selfservice.countdown.timer();
            } else {
              // Failed to ping, so logout
              selfservice.redirect(selfservice.pages.home, true);
            }
          },
          error: function(response) {
            // This could happen if Tomcat is unavailable during the check, let's kick start it.
            selfservice.session.kickstart();
          }
        });
      }
    };

    selfservice.session.kickstart = function () {
      setTimeout(function () {
        initializeSessionTimerChecks();
        selfservice.session.continueSession();
      }, 45 * 1000);
    };

    /**
     * Make a synchronous call to the server ping page to tell the server to keep the session alive.
     */
    selfservice.session.continueSession = function () {
        $.ajax({
            type: 'GET',
            url: selfservice.pages.ping,
            global: false,
            error: function(response) {
              selfservice.session.kickstart();
            }
        }).done(function(resultObject) {
            selfservice.countdown.timer();
        });
    };

    /**
     * Log the session out with the logout page, then go home.
     *
     */
    selfservice.session.logout = function () {
        selfservice.session.userLoggedIn = false;

        selfservice.logoutServer(selfservice.pages.logout);

        // If a user is logged in and is using a subscription,
        // clear their subscription countdown timer
        if (selfservice.subscriptionTimer.isTimerRunning) {;
        	selfservice.subscriptionTimer.clearTimer();
        }
    };



	 selfservice.logoutServer = function(submitUrl) {

		$.ajax({
			type : 'GET',
			url : submitUrl,
			success : function(response) {
				if (response != undefined && response != "") {

					if (response.success == true) {

						if (selfservice.validation.messages) {
							selfservice.validation.messages.empty();
						}
						var isKioskMode = '${selfService.kioskMode}';
						if (isKioskMode) {
							removeDisclaimerCookie();
						}
							window.location.replace(selfservice.pages.home);

					} else {
						console.log(response.message)
						selfservice.validation.messages.push(response.message)
					}

				}
			},
			error : function(jqXHR, textStatus, errorThrown) {

			}
		});
	}


    /**
	 * Timer: Call keepAlive every 10 seconds to see if the session is still
	 * valid.
	 *
	 */
    selfservice.countdown.timer = function () {
        var now = new Date().getTime();
        var sessionCheck = 10 * 1000;  // 10 seconds

        // If a timeout already exists, clear it while we still have a reference to it.
        if (selfservice.session.timeout) {
            clearTimeout(selfservice.session.timeout);
        }
        // Schedule the next invocation, in case everything goes right
        selfservice.session.timeout = setTimeout(selfservice.session.keepAlive, sessionCheck);

        // In case a beat was missed, cancel the timeout, and just go from there, setting a new rhythm
        if (new Date().getTime() - now > sessionCheck) {
            clearTimeout(selfservice.session.timeout);
            setTimeout(selfservice.session.keepAlive());
        }
    };

    /**
     * Checks certain conditions to determine if we
     * should keep a session running indefinitely.
     *
     */
    selfservice.session.shouldSessionRunForever = function() {
      // if we're not in kiosk mode (in web mode) run the session forever.
      var isKioskMode = selfservice.mode.kioskMode;
      if (!isKioskMode) {
        return true;
      }

      if(window.location.href.indexOf(selfservice.pages.disclaimer) > -1){
    	  return true;
      }

      // check if a user is logged in
      var isUserLoggedIn = selfservice.session.userLoggedIn;

      // check if the cart is empty
      var isCartEmpty = /\d/g.test($("#ss-cart-count-label").text()) ? false : true; // does the count label contain a number?

      // check if we're currently on the home page
      var isHomePage = selfservice.url.isHomePage(window.location.href);

      // If no user is logged in, the cart is empty and we're on the home page, run the session forever.
      if (!isUserLoggedIn && isCartEmpty && (isHomePage && !selfservice.setting.showDisclaimer)) {
        return true;
      }
      return false;
    };
    /////////////////////////
    // end Session Timeout
    /////////////////////////

    /////////////////////////
    // Subscription Timer
    /////////////////////////
    // initialize object
    selfservice.subscriptionTimer = {};

    // initialize variables
    selfservice.subscriptionTimer.subscriptionTime;
    selfservice.subscriptionTimer.isTimerRunning;
    selfservice.subscriptionTimer.timer;

    // declare methods
    selfservice.subscriptionTimer.setSubscriptionTime;
    selfservice.subscriptionTimer.getSubscriptionTime;
    selfservice.subscriptionTimer.startTimer;
    selfservice.subscriptionTimer.clearTimer;
    selfservice.subscriptionTimer.countdown;

    // method definitions
    /**
     * Gets the time (in milliseconds) of the subscription with the earliest expiration date
     * of the current user and sets that time to selfservice.subscriptionTimer.time.
     */
    selfservice.subscriptionTimer.setSubscriptionTime = function(elementId, url) {
    	$.ajax({
    		type: 'POST',
    		url: url,
    		global:false,
    		success: function(response) {
    			if (response != undefined && response != "") {
    				selfservice.subscriptionTimer.subscriptionTime = new Date(response);
    				selfservice.subscriptionTimer.startTimer(elementId, selfservice.subscriptionTimer.subscriptionTime);
    			}
    		},
    		error: function(jqXHR, textStatus, errorThrown) {
                // This could happen if Tomcat is unavailable during the subscription time retrieval
    		}
    	});
    };

    /**
     * Runs the countdown timer.
     */
    selfservice.subscriptionTimer.startTimer = function(elementId, subscriptionTime) {
    	if (!selfservice.subscriptionTimer.isTimerRunning) {
    		selfservice.subscriptionTimer.isTimerRunning = true;
    		selfservice.subscriptionTimer.timer = setInterval(function() {
    			selfservice.subscriptionTimer.countdown(elementId, subscriptionTime);
    		}, 500);
    	}
    };

    /**
     * Clears and stops the countdown timer.
     */
    selfservice.subscriptionTimer.clearTimer = function() {
		clearInterval(selfservice.subscriptionTimer.timer);
		selfservice.subscriptionTimer.isTimerRunning = false;
		$('#subscriptionTimer').text("");
    }

    /**
     * Creates the HTML that displays a countdown of
     * when the user's subscription will expire. This
     * function also will clear the timer when the
     * time expires.
     */
    selfservice.subscriptionTimer.countdown = function(elementId, subscriptionTime) {
    	var currentTime = new Date();
    	var countdownTime = new Date(subscriptionTime - currentTime);

    	if (countdownTime >= 0) {
    		// get time units based upon time since UNIX epoch
    	    var seconds = Math.floor(countdownTime.getTime() / 1000);
    	    var minutes = Math.floor(seconds / 60);
    	    var hours = Math.floor(minutes / 60);
    	    var days = Math.ceil(hours / 24);

    	    if (hours >= 24) {
        	    $('#' + elementId).text(messageStrings[selectedLanguage].Page_subscription_message_subscriptionTimerDays +
        	    		' ' + days);
    	    } else {
    	    	hours %= 24;
    	    	minutes %= 60;
    	    	seconds %= 60;

    	    	if (hours.toString().length == 1) {
    	    		hours = "0" + hours;
    	    	}

    	    	if (minutes.toString().length == 1) {
    	    		minutes = "0" + minutes;
    	    	}

    	    	if (seconds.toString().length == 1) {
    	    		seconds = "0" + seconds;
    	    	}

    	    	$('#' + elementId).text(messageStrings[selectedLanguage].Page_subscription_message_subscriptionTimerHours +
    	    			' ' + hours + ':' + minutes + ':' + seconds);
    	    }
    	} else {
    		selfservice.subscriptionTimer.clearTimer();
    	}
    };
    /////////////////////////
    // end Subscription Timer
    /////////////////////////

    /////////////////////////
    // slide in panels
    /////////////////////////
    selfservice.panel = {};

    /**
     * Safely close a panel without causing any errors
     */
    selfservice.panel.close = function (selfServicePanelLogin) {
        if (selfServicePanelLogin) {
            if (selfServicePanelLogin.hasClass('ui-panel-open')) {
                selfServicePanelLogin.panel('close');
            }
        }
    };
    /////////////////////////
    // end slide in panels
    /////////////////////////

    /////////////////////////
    // Browser Checker
    /////////////////////////
    selfservice.browserChecker = {};

    selfservice.browserChecker.isEdge = function() {
    	return /Edge\/\d./i.test(navigator.userAgent);
    }
    /////////////////////////
    // end Browser Checker
    /////////////////////////

    /**
     * selfservice.accountHistory - This object contains the URL parameters that
     * are passed into the GET request when a user requests an export of their
     * account history.
     */
    selfservice.accountHistory = {};
    selfservice.accountHistory.exportCsvButton;
    selfservice.accountHistory.exportPdfButton;
    selfservice.accountHistory.urlParams = '';

    selfservice.info = {};
    selfservice.info.message;
    selfservice.info.messageElement;

    /**
     * This object is used to populate form values during checkout so that they can be sent to BridgePay.
     * This is populated in cart.footer.jsp and used in bridgePayRedirect.body.jsp.
     */
    selfservice.checkout = {};
    selfservice.checkout.name = '';
    selfservice.checkout.email = '';
    selfservice.checkout.phone = '';
    selfservice.checkout.address1 = '';
    selfservice.checkout.address2 = '';
    selfservice.checkout.city = '';
    selfservice.checkout.state = '';
    selfservice.checkout.zip = '';

    /*
     * Add informational message to any element with .ss-info-message class.
     *
     */
    selfservice.info.addMessage = function (message) {
        selfservice.info.messageElement = $(".ss-info-message");
        if (!_.isEmpty(message)) {
            selfservice.info.messageElement.append('<ul><li>' + message + '</li></ul>');
        }
    };

    selfservice.passwordValidation = {};
    selfservice.passwordValidation.messages = $(".ss-passwordValidation-messages");

    selfservice.passwordValidation.addMessage = function(validationMessage, notEscaped) {
    	var errors = [];
    	var fields = [];
    	if(_.isString(validationMessage)) {
    		errors.push(validationMessage);
    	} else if(_.isArray(validationMessage)) {
    		errors = validationMessage;
    	} else if(_.isObject(validationMessage)) {
    		errors = _.values(validationMessage);
    		fields = _.keys(validationMessage);
    	}

    	if (!_.isEmpty(fields) && !_.isEmpty(errors)) {
    		$('.ss-passwordValidation-messages').each(function(index, element) {
    			if($(element).children('ul').length == 0) {
    				$(element).append('<ul></ul>');
    			}
    		});
    		_.each(fields, function(fieldId) {
    			var field = $("#"+fieldId);
    			var errorValue = _.property(fieldId)(validationMessage);
    			if (field.is('input')) {
    				var label = $("label[for="+fieldId+"]");
    				addErrors(label, field, errorValue);
    			} else {
    				$('<li>' + _.escape(errorValue) +  '</li>')
    				.appendTo(".ss-passwordValidation-messages ul");
    			}
    		});
    	} else if(!_.isEmpty(errors)) {
    		$('.ss-passwordValidation-messages').each(function(index, element) {
    			if($(element).children('ul').length == 0) {
    				$(element).append('<ul></ul>');
    			}
    		});

    		_.each(errors, function(errorValue) {
    			if(notEscaped){
    				$('<li>' + errorValue +  '</li>')
    				.appendTo(".ss-passwordValidation-messages ul");
    			}else{
        		$('<li>' + _.escape(errorValue) +  '</li>')
    				.appendTo(".ss-passwordValidation-messages ul");
    			}
    		});
    	}
    };

    selfservice.validation = {};
    selfservice.validation.messages = $(".ss-validation-messages");

    /**
     * Adds validation errors to the page under any element with the .ss-validation-message class.
     * This method will take either a string, array or object/map. It does not clear out any existing errors.
     *
     * @param validationErrors errors to add to the validation message elements
     * @param notEscaped is used when you want special characters in your error messages
     */
    selfservice.validation.addValidationErrors = function(validationErrors, notEscaped) {
    	$('html,body').scrollTop(0);

    	var errors = [];
    	var fields = [];
    	if(_.isString(validationErrors)) {
    		errors.push(validationErrors);
    	} else if(_.isArray(validationErrors)) {
    		errors = validationErrors;
    	} else if(_.isObject(validationErrors)) {
    		errors = _.values(validationErrors);
    		fields = _.keys(validationErrors);
    	}

    	if (!_.isEmpty(fields) && !_.isEmpty(errors)) {
    		$('.ss-validation-messages').each(function(index, element) {
    			if($(element).children('ul').length == 0) {
    				$(element).append('<ul></ul>');
    			}
    		});
    		_.each(fields, function(fieldId) {
    			var field = $("#"+fieldId);
    			var errorValue = _.property(fieldId)(validationErrors);
    			if (field.is('input')) {
    				var label = $("label[for="+fieldId+"]");
    				addErrors(label, field, errorValue);
    			} else {
    				$('<li>' + _.escape(errorValue) +  '</li>')
    				.appendTo(".ss-validation-messages ul");
    			}
    		});
    	} else if(!_.isEmpty(errors)) {
    		$('.ss-validation-messages').each(function(index, element) {
    			if($(element).children('ul').length == 0) {
    				$(element).append('<ul></ul>');
    			}
    		});

    		_.each(errors, function(errorValue) {
    			if(notEscaped){
    				$('<li>' + errorValue +  '</li>')
    				.appendTo(".ss-validation-messages ul");
    			}else{
        		$('<li>' + _.escape(errorValue) +  '</li>')
    				.appendTo(".ss-validation-messages ul");
    			}
    		});
    	}
    };

    selfservice.search = {};

    selfservice.search.responseElement;
    selfservice.search.resultsUrl;
    selfservice.search.filterUrl;
    selfservice.search.buttons;

    /**
     * Initializes selfservice search objects that are used across the
     * search screen and the search results themselves
     */
    selfservice.search.initializeSearchObjects = function(responseElement, resultsUrl, filterUrl, buttons) {
    	selfservice.search.responseElement = responseElement;
        selfservice.search.resultsUrl = resultsUrl;
        selfservice.search.filterUrl = filterUrl;
        selfservice.search.buttons = buttons;
    };

  // Fast empty from http://jsperf.com/removechildren/8
    function fastEmpty(container) {
		if (container[0].childNodes) {
			var len = container[0].childNodes.length;
			while (len--) {
				container[0].removeChild(container[0].lastChild);
			}
		}
	}	

    /**
	 * Perform a search
	 *
	 * @param responseElement
	 *            element to append the search results to
	 * @param resultsUrl
	 *            the URL of the search results
	 * @param searchForm
	 *            the search form element from the DOM
	 * @param searchButtons
	 *            the search button elements from the DOM
	 * @param resultButtons
	 *            the result button elements from the DOM
	 */
    selfservice.search.performSearch = function(responseElement, resultsUrl, filterUrl, searchForm, searchButtons, resultButtons) {
		
		fastEmpty($(responseElement));
		responseElement.append("<h2>" + messageStrings[selectedLanguage].Page_search_message_peformingSearch + "</h2>");
		responseElement.trigger('create');
		fastEmpty($(resultButtons));
		searchButtons.find("[data-role='button']").addClass('ui-disabled');
		$.ajax({
			type:"POST",
			url: searchForm.attr("action"),
			dataType: "json",
			data: searchForm.serializeArray(),
			error: function(jqXHR, textStatus, errorThrown){
				fastEmpty($(responseElement));
				responseElement.append("<h2>" + messageStrings[selectedLanguage].Page_search_message_searchFailed + "</h2>");
				responseElement.trigger('create');
			}
		}).done(function(resultObject) {
			console.dir(resultObject);
			var validationData = resultObject.validationMessages;
			if(_.isEmpty(validationData)) {
				selfservice.search.loadSearchResults(responseElement, resultsUrl, resultsUrl+"?page="+resultObject.currentPage, filterUrl, resultButtons, resultObject.currentPage, resultObject.totalPages, 1000);

			} else {
				// Failed server-side validation
				selfservice.validation.addValidationErrors(validationData);
				fastEmpty($(responseElement));
			}
		}).complete(function() {
			// Make sure the Search button doesn't stay highlighted
			searchButtons.find("[data-role='button']").removeClass('ui-disabled');
			searchButtons.find("#searchButton").removeClass("ui-btn-active").blur();
			searchButtons.trigger('create');
		});
    };

    /**
     * Load recent search results
     *
     * @param responseElement element to append the search results to
     * @param searchUrl the URL of the search page
     * @param resultsUrl the URL of the search results
     * @param searchButtons the search button elements from the DOM
     * @param resultButtons the result button elements from the DOM
     */
    selfservice.search.loadRecentResults = function(responseElement, searchUrl, resultsUrl, filterUrl, searchButtons, resultButtons) {
    	fastEmpty($(responseElement));
		responseElement.append("<h2>" + messageStrings[selectedLanguage].Page_search_message_peformingSearch + "</h2>");
		responseElement.trigger('create');
		fastEmpty($(resultButtons));

		$.ajax({
			type:"POST",
			url: searchUrl,
			dataType: "json",
			error: function(jqXHR, textStatus, errorThrown){
				fastEmpty($(responseElement));
				responseElement.append("<h2>" + messageStrings[selectedLanguage].Page_search_message_recentSearchNotAvailable + "</h2>");
				responseElement.trigger('create');
			}
		}).done(function(resultObject){
				var validationData = resultObject.validationMessages;
				if(_.isEmpty(validationData)) {
					resultsUrl = resultsUrl + resultObject.actionId;
					selfservice.search.loadSearchResults(responseElement, resultsUrl, resultsUrl+"?page="+resultObject.currentPage, filterUrl, resultButtons, resultObject.currentPage, resultObject.totalPages, 1000);

				} else {
					// Failed server-side validation
					selfservice.validation.addValidationErrors(validationData);
					fastEmpty($(responseElement));
				}
				searchButtons.find("#searchButton").removeClass("ui-btn-active").blur();
				searchButtons.trigger('create');
		});
    };

    /**
     * Load search Results
     *
     * @param responseElement element to append the search results to
     * @param resultsUrl the URL of the search results
     * @param searchUrl the URL of the search page
     * @param buttons the result button elements from the DOM
     * @param currentPage current selected page in the search results
     * @param totalPages total number of result pages
     * @param scrollTime how long the scroll should take in milliseconds
     * @param anchor the anchor to the document that we want to scroll to
     */
    selfservice.search.loadSearchResults = function(responseElement, resultsUrl, searchUrl, filterUrl, buttons, currentPage, totalPages, scrollTime, anchor) {
      $.ajax({
        url: searchUrl,
        type: "GET",
        error: function(jqXHR, textStatus, errorThrown) {
          fastEmpty($(responseElement));
          responseElement.append("<h2>" + messageStrings[selectedLanguage].Page_search_message_searchResultsUnavailable + "</h2>");
          responseElement.trigger('create');
        }
      }).done(function(searchResults) {

      	var html = $(searchResults);
      	fastEmpty($(responseElement));

        selfservice.search.addClickHandler(html, buttons, resultsUrl, filterUrl, currentPage, totalPages);
        if (filterUrl != null) {
          selfservice.search.addFilterHandler(html, buttons, resultsUrl, filterUrl);
        }
        selfservice.search.buildSearchButtons(html, buttons, resultsUrl, filterUrl, currentPage, totalPages);
        html.children('.ss-listview').listview('refresh');
        responseElement.append(html);
        responseElement.trigger("create");

        let padding = 22;
        if (!anchor) {
          anchor = 'resultAnchor';
          padding = 0;
        }
        selfservice.search.scrollToAnchor(anchor, scrollTime, padding);
        $("a#clearAllFilters").on("click", function(){
			dimensionsArray=[];
			pathsArray = [];
			$(".ui-controlgroup-control a").removeClass("selectedFacet");
			$(".ss-search-pill").each(function(index, element){
				var li = $(element);
				var dimension = li.data('dimension');
				var paths = li.data('paths');
				dimensionsArray.push(dimension);
				pathsArray.push(paths)
			});

			var filterPostUrl = filterUrl+"?searchDimension="+encodeURIComponent(dimensionsArray.join("|"))+"&paths="+encodeURIComponent(pathsArray.join("|"));
			selfservice.search.postSearchUrl(filterPostUrl, responseElement, buttons, resultsUrl, filterUrl);
		});
      });
    };

    var dimensionsArray = [];
    var pathsArray= [];

	selfservice.search.addFilterHandler = function(responseElement, buttons, resultsUrl, filterUrl) {
		$(responseElement).find("div.ss-search-pill").on('click', function() {
			var li = $(this);
			var dimension = li.data('dimension');
			var paths = li.data('paths');
			var dArray = [dimension];
			var pArray = [paths];
			var filterPostUrl = filterUrl+"?searchDimension="+encodeURIComponent(dArray.join("|"))+"&paths="+encodeURIComponent(pArray.join("|"));
			selfservice.search.postSearchUrl(filterPostUrl, responseElement, buttons, resultsUrl, filterUrl);
		});

		$(responseElement).find("a.ss-facet-entry").on('click', function() {

			var li = $(this);
			$(li).toggleClass("selected-facet")
			var dimension = li.data('dimension');
			var paths = li.data('paths');
			if($(li).hasClass("selected-facet")){
				dimensionsArray.push(dimension)
				pathsArray.push(paths);
			}else
			{
				var dimensionIndex = dimensionsArray.indexOf(dimension);
				var pathIndex = pathsArray.indexOf(paths);
				if(dimensionIndex > -1)
				{
					dimensionsArray.splice(dimensionIndex, 1);
				}
				if(pathIndex > -1)
				{
					pathsArray.splice(pathIndex, 1)
				}
			}
			if(dimensionsArray.length > 0)
			{
				$(".update-search-results").removeClass('ui-disabled');
			}else{
				$(".update-search-results").addClass('ui-disabled');
			}

			$("a.update-search-results").off("click");
			$("a.update-search-results").on("click", function(){
				var filterPostUrl = filterUrl+"?searchDimension="+encodeURIComponent(dimensionsArray.join("|"))+"&paths="+encodeURIComponent(pathsArray.join("|"));
				selfservice.search.postSearchUrl(filterPostUrl, responseElement, buttons, resultsUrl, filterUrl);
			})
			$(li).blur();
		});
	};

	selfservice.search.viewMoreResults = function(element, moreResults) {
		var container = $(element).parents('[data-role="controlgroup"]').last();

		container.find('.ss-hidden-facet-entry').each(function() {
			if (moreResults) {
				$(this).show();
			} else {
				$(this).hide();
			}
		});
		if (moreResults) {
			container.find(".ss-view-more").css('display', 'none');
			container.find(".ss-view-less").css('display', 'block');
		} else {
			container.find(".ss-view-more").css('display', 'block');
			container.find(".ss-view-less").css('display', 'none');
		}
	};

	selfservice.search.postSearchUrl = function(searchUrl, responseElement, buttons, resultsUrl, filterUrl) {
		$("input.ss-facet-entry").checkboxradio('disable');
		$("a.ss-view-more").addClass('ui-disabled');
		$("a.ss-view-less").addClass('ui-disabled');
		$.ajax({
			type:"POST",
			url: searchUrl,
			error: function(jqXHR, textStatus, errorThrown) {
				fastEmpty($(responseElement));
				responseElement.append("<h2>" + messageStrings[selectedLanguage].Page_search_message_searchFailed + "</h2>");
				responseElement.trigger('create');
			}
		}).done(function(resultObject){
			var validationData = resultObject.validationMessages;
			if(_.isEmpty(validationData)) {
				selfservice.search.loadSearchResults(responseElement, resultsUrl, resultsUrl+"?page=1", filterUrl, buttons, 1, resultObject.totalPages, 1000);
			} else {
				// Failed server-side validation
				selfservice.validation.addValidationErrors(validationData);
				fastEmpty($(responseElement));
			}
		}).complete(function() {
			// Make sure the Search button doesn't stay highlighted
			dimensionsArray = [];
			pathsArray= [];
			buttons.find("[data-role='button']").removeClass('ui-disabled');
			buttons.find("#searchButton").removeClass("ui-btn-active").blur();
			buttons.trigger('create');
		});
	}

    /**
     * Add click handlers to table headers for sorting
     *
     * @param responseElement element to append the search results to
     * @param buttons the result button elements from the DOM
     * @param resultsUrl the URL of the search results
     * @param currentPage current selected page in the search results
	 * @param totalPages total number of result pages
     */
	selfservice.search.addClickHandler = function(responseElement, buttons, resultsUrl, filterUrl, currentPage, totalPages) {
		var sortPopup = $(responseElement).find(".selfServiceSort");
		var sortUL = sortPopup.find('ul');
		$(sortUL).children('li').each(function() {
			$(this).on('click', function(event) {
				var li = $(event.target);
				var sortId = li.data('sort-id');
				var sortAscending = li.data('sort-ascending');

				var searchUrl = resultsUrl+"?page="+currentPage+"&sortColumn="+sortId+"&sortAscending="+sortAscending;
				selfservice.search.loadSearchResults(responseElement, resultsUrl, searchUrl, filterUrl, buttons, currentPage, totalPages, 1000);
				sortPopup.popup('close');
			});
		});

    	$(responseElement).find('ul li[data-href]').click(function(event) {
    		var target = $(event.target);

    		// If the user clicked the "View" link, view the document
    		if (target.is('.selfServiceSearchResultNavigation') || target.parent().is('.selfServiceSearchResultNavigation')) {
    			var href = $(this).data('href');
    			window.location = href;
    			return;
    		}

    		// If the user clicked on one of the buttons, perform its action
    		if (target.is('a') || target.parent().is('a')) {
    			event.stopPropagation();
    			event.preventDefault();
    			var a = target;
    			if (a.parent().is('a')) {
    				a = a.parent();
    			}
    			var fn = a.data('function');
    			if (fn) {
        			eval(fn);
        			return;
    			}

    			var href = a.prop('href');
    			if (href) {
    				window.location = href;
    				return;
    			}

    		} else if (target.is('input.ss-facet-select')) {
    			// Clicked on one of the checkboxes
    			var checked = target.prop('checked');
    			var ul = $(this).parents('ul.selfServiceSearchResultList');
   				var iconsChecked = ul.find('input.ss-facet-select:checked');
    			ul.children().each(function(){
    				var li = $(this);
    				if (iconsChecked.length > 0) {
    					var thisInput = li.find('input.ss-facet-select');
    					thisInput.css('display', 'block');
    					li.find('input.ss-facet-select').css('display', 'block');
    					li.find('.ss-facet-avatar').css('display', 'none');
    					if (iconsChecked.length === 1 && thisInput.is(':checked')) {
    						// If there is only one checkbox checked and it happens to be this one, show the selection options
    						li.find('.ui-li-aside.ss-search-actions').css('display', 'block');
    					} else {
    						li.find('.ui-li-aside.ss-search-actions').css('display', 'none');
    					}
    				} else {
    					li.find('input.ss-facet-select').css('display', '');
    					li.find('.ss-facet-avatar').css('display', '');
    					li.find('.ui-li-aside.ss-search-actions').css('display', '');
    				}
    			});

    			var parentUl = ul.parents('ul.ss-listview');
    			var cartIcon = parentUl.find('.ss-selected-result-actions').find('.mdi-cart-plus');
    			var saveIcon = parentUl.find('.ss-selected-result-actions').find('.mdi-content-save');

    			// There won't be a cart icon to show if purchasing is not enabled
    			if (cartIcon.length > 0) {
	    			if (iconsChecked.length > 0) {
	    				cartIcon.show();
	    			} else {
	    				cartIcon.hide();
	    			}
    			}

    			if (saveIcon.length > 0) {
    				if (iconsChecked.length > 0) {
    					saveIcon.show();
    				} else {
    					saveIcon.hide();
    				}
    			}

    			return;
    		}

    		var hidden=false;
    		var li = $(this);
    		var ul = li.parents('ul.selfServiceSearchResultList');
    		// Hide/show the expanded rows in the table
    		var hiddenValues = li.find('.selfServiceSearchFullResult');
			hiddenValues.each(function() {
				if ($(this).css('display') == 'none') {
					// Using block instead of show() because show uses "display:inline"
					$(this).css('display', 'block');
					hidden = false;
				} else {
					$(this).hide();
					hidden = true;
				}
			});

			var iconsChecked = ul.find('input.ss-facet-select:checked');
			hiddenValues = li.find('.ss-facet-select');
			var selected = hiddenValues.is(':checked') || iconsChecked > 0;
			hiddenValues.each(function() {
				// Using display properties because hovering already makes the element visible and show() has no effect
				// Selection checkboxes become visible
				if (!selected) {
					if (hidden) {
						// This is counter-intuitive. When hiding, return to the original styling
						$(this).css('display', '');
					} else {
						$(this).css('display', 'block');
					}
				}
			});

			// Hide/show the search actions (print, view, etc.)
    		hiddenValues = li.find('.ss-search-actions');
			hiddenValues.each(function() {
				// Using display properties because hovering already makes the element visible and show() has no effect
				if (!selected) {
					if (hidden) {
						// This is counter-intuitive. When hiding, return to the original styling
						$(this).css('display', '');
					} else {
						$(this).css('display', 'block');
					}
				}
			});

			hiddenValues = li.find('.ss-facet-avatar');
			hiddenValues.each(function() {
				// Using display properties because hovering already makes the element visible and show() has no effect
				// Avatars become invisible
				if (!selected) {
					if (hidden) {
						// This is counter-intuitive. When hiding, return to the original styling
							$(this).css('display', '');
					} else {
						$(this).css('display', 'none');
					}
				}
			});

			// Add CSS properties to control the size and look of the first expanded row
			var collapsed = li.find('.selfServiceSearchResultCollapsed');
			var expanded = li.find('.selfServiceSearchResultExpanded');
			var related = li.find('.ss-search-related');
			collapsed.each(function() {
				$(this).removeClass('selfServiceSearchResultCollapsed');
				$(this).addClass('selfServiceSearchResultExpanded');
			});
			expanded.each(function() {
				$(this).removeClass('selfServiceSearchResultExpanded');
				$(this).addClass('selfServiceSearchResultCollapsed');
			});

			related.each(function() {
				if (!hidden) {
					var loaded = $(this).data('loaded');
					if (!loaded) {
						var fn = $(this).data('function');
						if (fn) {
							eval(fn);
							$(this).data('loaded', true);
						}
					}
					$(this).show();
				} else {
					$(this).hide();
				}
			});
			li.parent().listview('refresh');
    	});
	};

	/**
	 * Create search navigation buttons for moving forward, back, begin, end
	 *
	 * @param responseElement element to append the search results to
	 * @param buttons the result button elements from the DOM
	 * @param baseUrl the URL of the base page
	 * @param currentPage current selected page in the search results
	 * @param totalPages total number of result pages
	 */
	selfservice.search.buildSearchButtons = function(responseElement, buttons, baseUrl, filterUrl, currentPage, totalPages) {
		var searchUrl = baseUrl + "?page=";
		buttons.empty();
		var scrollTime = 1000;
		var $break = $("<div class='ss-clear'></div>");
		buttons.append($break);
		if (totalPages > 1) {
			var next = messageStrings[selectedLanguage].Standard_button_next;
			var page = messageStrings[selectedLanguage].Standard_phrase_page;
			var previous = messageStrings[selectedLanguage].Standard_button_previous;
			var selectedItems;

			if (currentPage > 1) {
				// button to return to the first page of search results
				$("<a data-role=\"button\" data-inline=\"true\" data-theme=\"b\" data-iconpos=\"right\">" + page + " 1</a>")
				.insertBefore($break)
				.click(function() {
					selectedItems = $('body').find('input.ss-facet-select:checked');
					if (selectedItems.length > 0) {
						selfservice.search.openSelectedItemsWarningPopup('selectedItemsWarningNewPage', 1);
						return;
					}

					selfservice.search.loadSearchResults(responseElement, baseUrl, searchUrl+1, filterUrl, buttons, 1, totalPages, scrollTime);
				});
				// button to previous page in search results
				$("<a data-role=\"button\" data-inline=\"true\" data-theme=\"b\" data-iconpos=\"right\">" + previous + "</a>")
				.insertBefore($break)
				.click(function() {
					selectedItems = $('body').find('input.ss-facet-select:checked');
					if (selectedItems.length > 0) {
						selfservice.search.openSelectedItemsWarningPopup('selectedItemsWarningNewPage', currentPage - 1);
						return;
					}

					selfservice.search.loadSearchResults(responseElement, baseUrl, searchUrl+(currentPage-1), filterUrl, buttons, currentPage - 1, totalPages, scrollTime);
				});
			} else {
				// button to return to the first page of search results, disabled because we're on the first page
				$("<a class=\"ui-disabled\" data-role=\"button\" data-inline=\"true\" data-theme=\"b\" data-iconpos=\"right\">" + page + " 1</a>")
				.insertBefore($break);
				// button to previous page in search results, disabled because we're on the first page
				$("<a class=\"ui-disabled\" data-role=\"button\" data-inline=\"true\" data-theme=\"b\" data-iconpos=\"right\">" + previous + "</a>")
				.insertBefore($break);
			}

			// show the "page x of total"
			$("<inline-header-bolded> " + page + " " + currentPage + " " + messageStrings[selectedLanguage].Standard_phrase_of + " " + totalPages + "</inline-header-bolded>")
				.insertBefore($break);

			// forwardPages
            if (currentPage < totalPages) {
            	// button to next page in search results
                $("<a data-role=\"button\" data-inline=\"true\" data-theme=\"b\" data-iconpos=\"right\">" + next + "</a>")
                .insertBefore($break)
				.click(function() {
					selectedItems = $('body').find('input.ss-facet-select:checked');
					if (selectedItems.length > 0) {
						selfservice.search.openSelectedItemsWarningPopup('selectedItemsWarningNewPage', currentPage + 1);
						return;
					}

					selfservice.search.loadSearchResults(responseElement, baseUrl, searchUrl+(currentPage+1), filterUrl, buttons, currentPage + 1, totalPages, scrollTime);
				});
                // button to last page in search results
				$("<a data-role=\"button\" data-inline=\"true\" data-theme=\"b\" data-iconpos=\"right\">" + page + " " + totalPages + "</a>")
				.insertBefore($break)
				.click(function() {
					selectedItems = $('body').find('input.ss-facet-select:checked');
					if (selectedItems.length > 0) {
						selfservice.search.openSelectedItemsWarningPopup('selectedItemsWarningNewPage', totalPages);
						return;
					}

					selfservice.search.loadSearchResults(responseElement, baseUrl, searchUrl+totalPages, filterUrl, buttons, totalPages, totalPages, scrollTime);
				});
			} else {
				// button to next page in search results, disabled because we're on the last page
				$("<a class=\"ui-disabled\" data-role=\"button\" data-inline=\"true\" data-theme=\"b\" data-iconpos=\"right\">" + next + "</a>")
				.insertBefore($break);
				// button to last page in search results, disabled because we're on the last page
				$("<a class=\"ui-disabled\" data-role=\"button\" data-inline=\"true\" data-theme=\"b\" data-iconpos=\"right\">" + page + " " + totalPages + "</a>")
				.insertBefore($break);
			}
			buttons.children().wrapAll("<div class='ss-content' align='center' />");
			buttons.trigger('create');
		}
	};

    /**
     * Scroll to given anchor
     *
     * @param anchorId element id of the anchor to scroll to
     * @param loadTime how long the scroll should take in milliseconds
     * @param padding amount of extra space to allow for the scroll height
     */
    selfservice.search.scrollToAnchor = function(anchorId, loadTime, padding) {
      let anchorTag = $("a[id='"+ anchorId +"']");

      // header height seems to calculate differently on different browsers
      let headerHeight = $("[data-role=header]:visible").height();

      let offset = anchorTag.offset();
      if (!offset) {
        offset = anchorTag;
      }
      if (!padding) {
        padding = 0;
      }
      $('html,body').animate({scrollTop: offset.top-headerHeight-padding}, loadTime);
    };


	/**
	 * Open the warning popup that lets the user know that their
	 * selected search items will disappear if they perform another
	 * search or navigate to another page of results.
	 */
    selfservice.search.openSelectedItemsWarningPopup = function(id, pageCount) {
    	var popup = $('#' + id).popup('open', {transition: 'pop'});

    	if (pageCount !== undefined) {
    		$('<div id="pageCount" style="display: none;" data-value="' + pageCount + '"></div>').appendTo('body');
    	}
    };

	/**
	 * Close the warning popup that lets the user know that their
	 * selected search items will disappear if they perform another
	 * search or navigate to another page of results.
	 */
	selfservice.search.closeSelectedItemsWarningPopup = function(id) {
    	var popup = $('#' + id).popup('close', {transition: 'pop'});

    	$('body').find('#searchButton').removeClass('ui-disabled');
    	$('body').find('#searchButton').removeClass('ui-btn-active').blur();

    	if ($('#pageCount').length > 0) {
    		$('#pageCount').remove();
    	}

    	return false;
    };
    
	selfservice.search.openSortPopup = function(event, id, postitionToId) {
		event.stopPropagation();
		event.preventDefault();
		$(id).popup({tolerance: "0, 30, 0, 0"});
		$(id).popup("open", {positionTo: postitionToId, transition: "pop"});		
	};

	selfservice.document = {};

	selfservice.document.pdfJsUrl;

	/**
	 * Build buttons for navigating through search result documents on document screen
	 *
	 * @param buttons the result button elements from the DOM
	 * @param baseUrl the URL of the base page
	 * @param previousResult the previous page in the search results
	 * @param nextResult the next page in the search results
	 * @param searchPageUrl the URL of the search page
	 */
	selfservice.document.buildDocumentNavigationButtons = function(buttons, baseUrl, previousResult, nextResult, searchPageUrl){
		buttons.empty();

		var $break = $("<div class='ss-clear'></div>");
		var next = messageStrings[selectedLanguage].Page_search_button_next;
		var previous = messageStrings[selectedLanguage].Page_search_button_previous;

		buttons.append($break);
		if(nextResult!= null && nextResult !=""){
			$("<a data-role=\"button\" data-inline=\"true\" data-theme=\"b\" data-iconpos=\"right\">" + next + "</a>")
			.insertAfter($break)
			.click(function() {
				selfservice.document.currentDocumentNumber = nextResult;
				selfservice.redirect(baseUrl+nextResult+searchPageUrl, true);
			});
		} else {
			$("<a class=\"ui-disabled\" data-role=\"button\" data-inline=\"true\" data-theme=\"b\" data-iconpos=\"right\">" + next + "</a>")
			.insertAfter($break);
		}
		if(previousResult!=null && previousResult!=""){
			$("<a data-role=\"button\" data-inline=\"true\" data-theme=\"b\" data-iconpos=\"right\">" + previous + "</a>")
			.insertAfter($break)
			.click(function() {
				selfservice.document.currentDocumentNumber = previousResult;
				selfservice.redirect(previousResult+searchPageUrl, true);
			});
		} else {
			$("<a class=\"ui-disabled\" data-role=\"button\" data-inline=\"true\" data-theme=\"b\" data-iconpos=\"right\">" + previous + "</a>")
			.insertAfter($break);
		}
		buttons.children().wrapAll("<div class='ss-content' align='left' />");
		buttons.trigger('create');
	};

	/**
	 * Build footer on document screen
	 *
	 * @param footer
	 * @param forwardUrl
	 */
	selfservice.document.buildFooter = function(footer, forwardUrl) {
		// CONSIDER: Should probably put a 'back to search' button as well
		var $clear=$("<div class='ss-clear'></div>");
		footer.empty();
		footer.append($clear);

		var select = messageStrings[selectedLanguage].Standard_button_select;
		if (forwardUrl.length > 0) {
			$("<a class=\"ss-right\" data-role=\"button\" data-inline=\"true\" data-theme=\"b\" data-iconpos=\"right\">" + select + "</a>")
		    .click(function() {
		    	selfservice.redirect(forwardUrl, true);
		    })
		    .insertBefore($clear);
		}
		$(".ss-footer-stripe").children().wrapAll("<div class='ss-content' />");
		footer.trigger('create');
	};

    /**
     * Use this event when binding new on events to the document.
     * This method will unbind any previously bound functions to the event
     * and bind the function that was passed in to the event.
     *
     * @param event The event that is being triggered.(keyup, keypressed, click, etc)
     * @param handler Function to be executed when event is triggered.
     */
    selfservice.document.rebindOnEvents = function(event, handler){
    	$(document).off(event);
    	$(document).on(event, handler);
    };

    selfservice.user = {};

    /**
     * Update the header message to welcome the user when logged in
     *
     * @param messageDiv the element to add the message to
     * @param loggedIn true if a user is logged in
     * @param userName name of the user to welcome
     */
    selfservice.user.updateUserMessage = function(messageDiv, loggedIn, userName) {
    	$(messageDiv).empty();
    	var message = '';
    	if (loggedIn) {
    		message = messageStrings[selectedLanguage].Page_header_message_welcome + ' ' + userName;
    	} else {
    		message = messageStrings[selectedLanguage].Page_header_message_login;
    	}

    	$(messageDiv).append(message);
    };

    /**
     * Check that password and confirm password match
     *
     * @param regularFieldId id of the password field
     * @param regularLabelId id of the label for the password field
     * @param confirmFieldId id of the confirm password field
     * @param confirmLabelId id of the label for the confirm password field
     */
    selfservice.user.checkPassword = function(regularFieldId, regularLabelId, confirmFieldId, confirmLabelId) {
		var password = $(regularFieldId).val();
		var confirmPassword = $(confirmFieldId).val();
		clearErrors($(regularLabelId),$(regularFieldId));
		clearErrors($(confirmLabelId),$(confirmFieldId));

		if (password.length > 0 && confirmPassword.length > 0) {
			if (password != confirmPassword) {
				var pwlabel = $(regularLabelId);
				var pwfield = $(regularFieldId);
				var cpwlabel = $(confirmLabelId);
				var cpwfield = $(confirmFieldId);
				var message = messageStrings[selectedLanguage].Page_profile_message_passwordsDoNotMatch;
				addFieldErrors(pwlabel, pwfield, message);
				addFieldErrors(cpwlabel, cpwfield, message);
				selfservice.validation.addValidationErrors(message);
				return false;
			}
		}
		return true;
	};

    /**
     * Show or hide the billing section based on checkbox
     *
     * @param checkField the checkbox to look at
     * @param dataField the data field to show/hide
     */
	selfservice.user.showHideBilling = function(checkField, dataField) {
		if ($(checkField).is(':checked')) {
			$(dataField).parentsUntil('.ui-grid-b').parent().parent().hide();
		} else {
			$(dataField).parentsUntil('.ui-grid-b').parent().parent().show();
		}
	};

    /**
	 * Format date as MM/DD/YYYY
	 *
	 * @param date the date to format
	 * @return the formatted date as MM/DD/YYYY
	 */
	selfservice.formatDateMMDDYYYY = function (date) {
	    // Javascript gets the date wrong if you send it in with dashes (it thinks they mean minus).
	    if (typeof(date) == 'string') {
	        date = date.replace('-', ',');
	    }
	    var d = new Date(date);

	    var dd = d.getDate();
	    var mm = d.getMonth() + 1; //January is 0!
	    var yyyy = d.getFullYear();

	    if (dd < 10) {
	        dd = '0' + dd;
	    }

	    if (mm < 10) {
            mm = '0' + mm;
        }

	    return mm + '/' + dd + '/' + yyyy;
	};

    /**
     * Parse a date
     *
     * @param elem the element containing the date, parsed date is placed in this element
     * @param minDate the minimum allowed date, set to this if date is earlier
     * @param maxDate the maximum allowed date, set to this if date is later
     */
    selfservice.parseDate = function(elem, minDate, maxDate) {
    	var elemId = $(elem).attr('id');
    	$("#" + elemId + "-yearError").remove();
    	// Try to split dates on dashes or slashes
    	var parsedVal = this.parseDateShortcuts($(elem).val());
    	var val = parsedVal == null ? $(elem).val() : parsedVal;
 
		var opera1 = val.split('/');
		var opera2 = val.split('-');
		var segments = opera1.length > opera2.length ? opera1 : opera2;

		var month = "";
		var day = "";
		var year = "";
		if (segments.length == 3) {
			if (segments[0].length > 2) {
				// handle yyyy-mm-dd or yyyy/mm/dd
				year = segments[0];
				month = segments[1];
				day = segments[2];
			} else {
				// handle mm-dd-yyyy or mm/dd/yyyy
				month = segments[0];
				day = segments[1];
				year = segments[2];
			}
		} else if (segments.length == 1) {
			if (val.length == 8) {
				month = val.substring(0, 2);
				day = val.substring(2, 4);
				year = val.substring(4, 8);
			} else {
				return null;
			}
		} else {
			return null;
		}

		var intM = parseInt(month);
		var intD = parseInt(day);
		var intY = parseInt(year);

		if (intY < 1000) {
			return null;
		}

		//put into a date so we can invalidate things like 06/31
		var d = new Date(intY, intM-1, intD);
		if (intM -1 == d.getMonth() && intD == d.getDate() && intY < 3000 && intY > 1000) {
			if (maxDate != null && d > maxDate) {
				month = "" + (maxDate.getMonth() + 1);
				day = "" + maxDate.getDate();
				year = "" + maxDate.getFullYear();
			}
			if (minDate != null && d < minDate) {
				month = "" + (minDate.getMonth() + 1);
				day = "" + minDate.getDate();
				year = "" + minDate.getFullYear();
			}
			$(elem).val(month + '/' + day + '/' + year);
		}

		return d;
    };

    /**
     * Create a valid date string to send to a browser.
     *
     * @param date an actual date object
     */
    selfservice.formatDate = function(date) {
        var day = date.getDate();
        var month = date.getMonth() + 1; //January is 0!
        var year = date.getFullYear();

        if (month == undefined) {
            year = 2000;
        } else {
            year = parseInt(year);
        }
        if (month == undefined) {
            month = 1;
        } else {
            month = parseInt(month);
        }
        if (day == undefined) {
            day = 1;
        } else {
            day = parseInt(day);
        }

        if (month < 10) {
            mm = '0' + month;
        } else if (month > 12) {
            mm = '01';
        } else {
            mm = month + '';
        }

        if (day < 10) {
            dd = '0' + day;
        } else if (day > 31) {
            dd = '01';
        } else {
            dd = day + '';
        }
        return mm + "/" + dd + "/" + year;
    };

    /**
     *
     * @param field
     */
    selfservice.dropdownfix = function addFocusEventListeners(field) {
      // Define named functions for each event handler
      function handleDDClick(event) {
          setTimeout(() => {
              field.focus();
          }, 50);
      }

      function handleDDChange(event) {
          setTimeout(() => {
              field.focus();
          }, 50);
      }

      function handleDDKeydown(event) {
          const key = event.which || event.keyCode;

          // Up arrow key
          if (key === 38) {
              setTimeout(() => {
                  field.focus();
              }, 50);
          }
          // Down arrow key
          else if (key === 40) {
              setTimeout(() => {
                  field.focus();
              }, 50);
          }
      }

      // Attach event listeners using addEventListener
      field.on('click', handleDDClick);
      field.on('change', handleDDChange);
      field.on('keydown', handleDDKeydown);
      //add them to the dataset so we can remove them later if element is cloned
      field.data('handleDDClick', handleDDClick);
      field.data('handleDDChange', handleDDChange);
      field.data('handleDDKeydown', handleDDKeydown);
  }

    /**
     * Create an input element
     *
     *  @param element the parent element to append the new input element to
     *  @param fieldName name attribute for the new input element
     *  @param fieldValue value attribute for the new input element
     */
    selfservice.createFormField = function(element, fieldName, fieldValue) {
    	element.append('<input type="hidden" name="' + fieldName + '" value="' + fieldValue + '"/>');
    };

    /**
     *
     * @param evt
     */
    selfservice.determineKeyCodeProperty = function(evt) {
    	return evt.keyCode ? evt.keyCode : evt.which;
    };

    /**
     *
     * @param key
     */
    selfservice.userPressedValidKeyForInputNumberTypeBox = function(key) {
    	if ((key >= 48 && key <= 57) || (key >= 96 && key <= 105) || key === 8 ||
    			key === 9 || key === 37 || key === 38 || key === 39 ||
    			key === 40 || key === 46 || key === 110 || key === 190) {
    		return true;
    	}

    	return false;
    };

    /**
     * Clear values from all text boxes of type text, number, hidden or date.
     *
     */
    selfservice.clearAllTextBoxes = function() {
    	var textBoxes = document.getElementsByTagName("input");
    	for (var i = 0; i < textBoxes.length; i++) {
    		var textBox = textBoxes[i];
    		if (textBox.type.toLowerCase() === "text" ||
    				textBox.type.toLowerCase() === "number" ||
    				textBox.type.toLowerCase() === "hidden" ||
    				textBox.type.toLowerCase() === "date") {
    			textBox.value = "";
    		}
    	}
    	var cbul = $('ul.cblist-input-list');
    	cbul.children().not('.cblist-input-toggle').remove();
    	cbul.hide();
    };

    /**
     * Truncate text in given elements
     *
     * @param elements list of elements to truncate
     * @param truncationLength max length of text
     */
    selfservice.truncateText = function(elements, truncationLength) {
    	for (var i = 0; i < elements.length; i++) {
    		var text = elements[i].textContent;
    		if (text.length > truncationLength) {
    			var truncatedText = text.replace(text.substring(truncationLength, text.length), "...");
    			elements[i].textContent = truncatedText;
    		}
    	}
    };

    /**
     * A boolean used to determine if all document types
     * need to be unchecked from a document type popup
     * within a search action
     */
    selfservice.uncheckAllDocumentTypes = false;

    /**
     * Sets a given element to call selfservice.changeNumberOfDaysInMonth()
     * when its value changes
     *
     *  @param id - the ID of the element
     */
    selfservice.registerClickHandlerForOptionalDateFields = function(id) {
    	$("#" + id).on("change", function() {
    		selfservice.changeNumberOfDaysInMonth();
    	});
    };

    /**
     * Changes the number of days within a optionalDate presentation given
     * a month and a year
     *
     * @param - month - the month field within the optionalDate composite
     * @param - year - the year field within the optionalDate composite
     */
    selfservice.changeNumberOfDaysInMonth = function() {
    	var month = $("select[id*=OptionalMonth]").val();
    	var year = $("select[id*=OptionalYear]").val();
    	if (month === "" || parseInt(month) > 12 ||
    			year === "") {
    		return;
    	}

    	// clear out the option elements
    	var daySelect = $("select[id*=OptionalDay]");
    	var currentValue = daySelect.val();
    	daySelect.empty();

    	// populate the new number of days inside the select
    	var daysInMonth = new Date(year, month, 0).getDate();
		var options = "<option value=''>--</option>";
		for (var i = 0; i < daysInMonth; i++) {
			var day = String(i + 1);
			if (day.length < 2) {
				day = "0" + day;
			}

			options += "<option value='" + day + "'>" + day + "</option>";
		}

		daySelect.append(options);

		if (parseInt(currentValue) < daysInMonth) {
			daySelect.val(currentValue);
		} else {
			daySelect.val("");
		}

		daySelect.selectmenu("refresh");
    };
    const AUTOCOMPLETE_TRIGGER_COUNT = 2;
    const AUTO_COMPLETE_MAX_VALUES = 1000;
    selfservice.suggest = {};

    //Get the last element clicked for autocomplete focusout
    var elementClicked;
    $(document).mousedown(function(e) {
    	elementClicked = $(e.target);
    });
    $(document).mouseup(function(e) {
    	elementClicked = null;
    });

    selfservice.suggest.autocomplete = function(inputField, listField, url, includeContains, showKeys, filterOnFocus) {
    	// Set up the Contains All/Any toggle
    	var containsId = $(inputField).prop('id')+"-containsInput";
    	var containsLi = $("<li class='cblist-input-toggle'></li>");

    	var containsAny = messageStrings[selectedLanguage].Page_suggest_containsAny;
    	var containsAll = messageStrings[selectedLanguage].Page_suggest_containsAll;

    	var containsAnyTooltip = messageStrings[selectedLanguage].Page_suggest_tooltip_containsAny;
    	var containsAllTooltip = messageStrings[selectedLanguage].Page_suggest_tooltip_containsAll;

    	// NOTE: Input values are expected to be in English, but we only display the text so don't translate values
   		containsLi.append("<p title='" + containsAnyTooltip + "'>"+containsAny+"</p>");
   		containsLi.append("<input type='hidden' id='"+containsId +"' name='" + containsId + "' value='Contains Any'>");

    	var $holder = $("#"+$(inputField).prop('id')+"-holder");
    	$holder.data('includeContains', includeContains);
    	$holder.find($(".cblist-input-list, .cblist-input-toggle")).remove();
    	$holder.prepend(containsLi);
    	containsLi.hide();

	    if (includeContains) {
	    	containsLi.on('click', function() {
	    		var containsP = $(this).children('p').first();
	    		var containsInput = $(this).children('input').first();
	    		var containsText = containsInput.val();
	    		if (containsText == 'Contains All') {
	    			containsP.html(containsAny);
	    			containsP.attr('title', containsAnyTooltip);
	    			containsInput.val('Contains Any');
	    		} else {
	    			containsP.html(containsAll);
	    			containsP.attr('title', containsAllTooltip);
	    			containsInput.val('Contains All' );
	    		}
	    	});
	    }

	    // HACK: Attach a listener so we know when we are over our list field. This is used by the focus out listener
	    var lf = $(listField);
	    var $input = $(inputField);

	    lf.mouseenter(function(event) {
	    	$(document).data('listFieldFocus', true);
	    }).mouseleave(function(event) {
	    	$(document).data('listFieldFocus', false);
	    });

    		var timeout = 0;
    		$input.off('focus');
    		$input.on('focus', function() {

    			$("ul[id$='aclist']").each(function(){
    				if(lf.attr("id") != $(this).attr("id")){
    					var inputId = $(this).attr('id').replace('-aclist', '');
    					$(this).hide()
    					$("#" + inputId).val("");
    				}
    		   	  });


    			$input.closest("ul").addClass("ui-focus");
    			if (filterOnFocus) {
	    			if ($(document).data('filterOnFocus') || lf.children().length > 0) {
	    				return;
	    			}

	    			$(document).data('filterOnFocus', true);
		    		lf.filterable('option', 'filterReveal', 'false');
		    		clearTimeout(timeout);
		    		timeout=setTimeout(selfservice.suggest.performFilter(lf, {'input' : $input}, url, includeContains, showKeys, filterOnFocus), 250);

	    			$(document).data('listFieldFocus', false);
    			}
    		});


    	$input.on('blur', function() {
    		$input.closest("ul").removeClass("ui-focus");
    	})




    	$input.off('focusout');
    	$input.on('focusout', function(event) {
    	    event.preventDefault();
            event.stopPropagation();

    		// Special handling so that the scroll bar (mouse inside the list field) and clear buttons work
    		var newOwner = $(event.relatedTarget);

    		if ($(document).data('listFieldFocus') || newOwner.is('a.ui-input-clear')) {
    			return;
    		}

    		// If we got this far, the user is tabbing away so any text should become search text as a chip
    		var searchText = selfservice.removeScriptTags($input.val());
			var $holder = $("#" + $input.prop('id') + "-holder");
    		if($(elementClicked).closest('ul.cblist-input-list')[0] === $holder[0]){
    			return;
    		}
			var cbinputs = $holder.find('li.cblist-input-list').length;
			if (searchText.length > 0) {
				if (cbinputs < 1) {
					selfservice.search.addSearchItem(searchText, searchText, $holder, $input, "-searchInput");
				}
				$input.val('');
			}

    		lf.data("maxValues", 0);
    		lf.empty();
    		lf.filterable("refresh");
    		lf.hide();
    		$(document).data('listFieldFocus', false);

    		lf.filterable('option', 'filterReveal', 'true');
    		$(document).data('filterOnFocus', false);

    	});

    	$(inputField).siblings('.ui-input-clear').on('click', function() {
    		$(listField).hide();
    		$(".autoCompleteList").addClass("noBorder");
    		$(document).data('listFieldFocus', false);
    	});

    	// Code adapted from jQuery Mobile listview autocomplete remote demo
    	$(listField).off('filterablebeforefilter');
    	$(listField).on ("filterablebeforefilter", function(e, data) {
    		selfservice.suggest.performFilter($(this), data, url, includeContains, showKeys, filterOnFocus);
    	});

    };

    var autocompleteResults;
    var autocompleteResultsPage;

    selfservice.suggest.performFilter = function ($ul, data, url, includeContains, showKeys, filterOnFocus) {

    	$(document).data('listFieldFocus', true);
		var $input = $(data.input),
		value = $input.val(),
		html = "";
		var $holder = $("#" + $input.prop('id') + "-holder");
		value = selfservice.sanitizeString(value);
		var append = false;
		var maxValues = $ul.data("maxValues");
		var lastMax = maxValues;
		if (!maxValues) {
			maxValues = AUTO_COMPLETE_MAX_VALUES;
		}

		$ul.data("maxValues", maxValues);
		$ul.data("lastValue", value);

		var searchUrl = url + "?searchText=" + encodeURIComponent(value) + "&maxValues=" + maxValues;
		$ul.empty();

		
			$ul.show();
			$ul.listview('refresh');

			if (value.length > 0) {
				var valLi = $ul.append('<li class="acItem acItem-selected" data-filtertext="' + value + '">' + value + '</li>');
				valLi.data("key", value);
				valLi.data("value", value);

			}

			if (filterOnFocus || (value && value.length > AUTOCOMPLETE_TRIGGER_COUNT)) {
				var loadingLi = $ul.append('<li class="acItem-loading " data-filtertext="' + value + '">'+messageStrings[selectedLanguage].Page_suggest_loadingResults+'<p class="acloader"></p></li>');
			$.ajax({
				type: 'POST',
				url: searchUrl,
				global: false
			})
			.error(function(jqXHR, textStatus, errorThrown) {
				$ul.append('<li class="acFinal error" data-filtertext="' + value + '">Error</li>');
			})
			.then(function(response) {
				$('li.acItem-loading').remove();
				if (response.length == 0) {
					$ul.append('<li class="acFinal" data-filtertext="' + value + '">'+messageStrings[selectedLanguage].Page_suggest_noResultsFound+'</li>');
				}

				if (response.toString().indexOf('<!DOCTYPE html>') != -1) {
					// Handle exceptions that show up as an error page
					$ul.append('<li class="acFinal error" data-filtertext="' + selfservice.sanitizeString(value) + '">'+messageStrings[selectedLanguage].Standard_error_message_titleError+'</li>');
					return;
				}
				var lastAppendedValues = $ul.data('lastSearchValues');
				var appendedValues = [];
				autocompleteResults = response;
			    autocompleteResultsPage = 0;
				// Pass two, append all previous values to the list
				if (append && lastAppendedValues) {
					$.each(response, function(i, val) {
						var key;
						if (val.name) {
							key = val.name;
						}else {
							key = val;
						}

						if (lastAppendedValues.indexOf(key) >= 0) {
							selfservice.search.appendValue(value, showKeys, val, $ul);
							appendedValues.push(key);
						}
					});
				}

				// Pass one, append all remaining values to the list
				$.each(response, function(i, val) {
					if (i >= maxValues) {
						return;
					}

					var key;
					if (val.name) {
						key = val.name;
					}else {
						key = val;
					}
					if (!append || !lastAppendedValues || (lastAppendedValues.indexOf(key) < 0)) {
						selfservice.search.appendValue(value, showKeys, val, $ul);
						appendedValues.push(key);
					}
				});

				$ul.data('lastSearchValues', appendedValues);

				if (response.length > maxValues) {
					var searchMoreLi = $("<li class='acFinal' data-filtertext='" + value + "'>" + maxValues + " of " + response.length + " " + messageStrings[selectedLanguage].Page_suggest_loadMore + "</li>");
					$ul.append(searchMoreLi);

					searchMoreLi.on('click', function() {
						selfservice.suggest.loadMoreResults($ul, data, url, includeContains, showKeys, filterOnFocus, value);
					});
				}



				$ul.filterable("refresh");
				$ul.children().removeClass('ui-screen-hidden');
				$ul.trigger("updatelayout");

				if (append) {
					var sep = $ul.find('li.acSeparator');
					if (sep) {
						var scrollAmount = sep.offset().top - $ul.offset().top + $ul.scrollTop();
						$ul.animate({scrollTop: scrollAmount}, 200);
					}
				}
			});
		}
	};

	$(document).on('click', 'li.acItem', function(event) {
		var inputId = $(this).closest('ul').attr('id').replace('-aclist', '');
		var $input = $("#"+inputId);
		var item = $(this);
		var key = item.data('key');
		var acItemvalue = item.data('value');
		var $holder = $('#' + $input.prop('id') + '-holder');
		var exists = false;
		$.each($holder.find("li.cblist-input-list"), function(index, value){
        	if($(value).text() === item.text())
       		{
        		$(value).css("background","lightblue");
	       		setTimeout(function(){
	       			$(value).css("background","initial");
	       	        },500);
	       		exists = true;
	       		return false;
       		}
        });
		if(!exists){
			if (key != undefined) {
				var key = $(this).data('key');
				var value = $(this).data('value');
				var $holder = $('#' + $input.prop('id') + '-holder');
				selfservice.search.addSearchItem(key, value, $holder, $input, '-holderInput');
			} else {
				var searchText = $input.val();
				if (searchText.length > 0) {
					var $holder = $('#' + $input.prop('id') + '-holder');
					searchText = selfservice.sanitizeString(searchText);
					selfservice.search.addSearchItem(searchText, searchText, $holder, $input, '-searchInput');
				}
			}
		}


		item.siblings().removeClass('acItem-next');
		item.siblings().removeClass('acItem-selected');
		if(item.next()){
			item.next().addClass('acItem-next');
		}else if(item.prev()){
			item.prev().addClass('acItem-next');
		}
		item.remove();
		$input.focus();
	});


	selfservice.suggest.loadMoreResults = function($ul, data, url, includeContains, showKeys, filterOnFocus, value)
	{
	    autocompleteResultsPage++;
	    var lastAppendedValues = $ul.data('lastSearchValues');
	    var appendedValues = [];

	    $ul.find('li.acFinal').detach();

		var slice = autocompleteResults.slice( autocompleteResultsPage * AUTO_COMPLETE_MAX_VALUES);

		$.each(slice, function(i, val) {
			if (i >= AUTO_COMPLETE_MAX_VALUES) {
				return;
			}
			var key;
			if (val.name) {
				key = val.name;
			}else {
				key = val;
			}

			if (lastAppendedValues.indexOf(key) < 0 ) {
				selfservice.search.appendValue(value, showKeys, val, $ul);
				appendedValues.push(key);
			}

		});

		if (slice.length > AUTO_COMPLETE_MAX_VALUES) {
			var searchMoreLi = $("<li class='acFinal' data-filtertext='" + value + "'>" + AUTO_COMPLETE_MAX_VALUES *  (autocompleteResultsPage + 1) + " of " + autocompleteResults.length + " " + messageStrings[selectedLanguage].Page_suggest_loadMore + "</li>");
			$ul.append(searchMoreLi);

			searchMoreLi.on('click', function() {
				selfservice.suggest.loadMoreResults($ul, data, url, includeContains, showKeys, filterOnFocus, value);
			});
		}

		$ul.data('lastSearchValues', appendedValues);
		$ul.filterable("refresh");
		$ul.children().removeClass('ui-screen-hidden');
		$ul.trigger("updatelayout");
	}

	selfservice.search.appendValue = function (value, showKeys, val, $ul) {
		// Passed in field/value
		if (val.name) {
			var text = "";

			if (showKeys) {
				text = val.name + " - " + val.value;
			} else {
				text = val.value;
			}

			var valLi = $('<li class="acItem truncate" data-filtertext="' + value + '">' + text + '</li>');
			$ul.append(valLi);
			valLi.data("key", val.name);
			valLi.data("value", val.value);
		} else {
			var valLi=$('<li class="acItem truncate" data-filtertext="' + value + '">' + val + '</li>');
			$ul.append(valLi);
			valLi.data("key", val);
			valLi.data("value", val);
		}
	}

	selfservice.search.addSearchItem = function(key, value, holder, input, inputSuffix) {
		var $holder = $(holder);
		var $input = $(input);
		var includeContains = $holder.data('includeContains');
		$holder.show();
		var liId = $input.prop('id') + inputSuffix;
		var li = $("<li class='cblist-input-list transition-background'></li>");

		key = key.replace("'", "&apos;");
		li.append("<p>" + value + "</p>");
		li.append("<input type='hidden' id='" + liId + "' name='" + liId + "' value='" + key + "'>");
		if(inputSuffix == '-holderInput') {
			var valueId = $input.prop('id') + '-holderValue';
			li.append("<input type='hidden' id='" + valueId + "' name='" + valueId + "' value='" + value + "'>");
		}
		var inputToggle = $holder.find(".cblist-input-toggle");
		inputToggle.before(li);

		// Two search items in the field, don't count the toggle field
		if (includeContains && $holder.find('li.cblist-input-list').length > 1) {
			inputToggle.show();
		}

		$(li).on('click', function() {
			li.remove();
			// Nothing left except the toggle field, no contains
			var cbinputs = $holder.find('li.cblist-input-list').length;
			if (cbinputs < 2) {
				inputToggle.hide();
			}
			$input.focus();
		});
		//li[0].parentElement.scrollIntoView({behavior: "smooth", block: "center", inline: "end"});
		if(!li.inView())
		{
			$('html, body').animate({
		        scrollTop: $(li).offset().top - 125
			}, 50);
		}

	};

	/**
	 * Script tags can leave us vulnerable to XSS if we evaluate them. So, drop them.
	 *  There is probably a more efficient way to do this, but it gets the job done.
	 */
	selfservice.removeScriptTags = function (value) {
		if ((/script/i).test(value)) {
			// replace all whitespace characters and
			// make all characters upper case first
			value = value.toUpperCase();
			value = value.replace(/\s/g, '');

			value = value.replace('&LT;SCRIPT&GT;', '');
			value = value.replace('&LT;/SCRIPT&GT;', '');
			value = value.replace('<SCRIPT>', '');
			value = value.replace('</SCRIPT>', '');
		}

	    return value;
	};

	selfservice.sanitizeString = function(value) {
		// Remove script tags
	    value = selfservice.removeScriptTags(value);

		// Replace special characters as HTML special characters
		value = value.replace(/&/g, "&amp;");
		value = value.replace(/>/g, "&gt;");
		value = value.replace(/</g, "&lt;");
		value = value.replace(/"/g, "&quot;");
		value = value.replace(/'/g, "&#039;");

		return value;
	};

    selfservice.navigate = {};
    selfservice.testvar;
    /**
     * Register update and down arrows to navigate a list. The parent field is the starting point to enter the list
     */
    selfservice.navigate.registerListNavigation = function(parentField, list) {
    	// Unbind existing events on the field so Enter works as expected
    	$(parentField).off('keydown');
    	$(parentField).off('keyup');
    	$(parentField).off('keypress');

    	selfservice.document.rebindOnEvents('keydown', function (e) {
    	    if (e.which != 13 && e.which != 38 && e.which != 40 && e.which != 9 && e.keyCode != 13 && e.keyCode != 38 && e.keyCode != 40 && e.keyCode !=9) {
    			return;
    		}
    	    selfservice.testvar = $(document.activeElement);
    		var focused = $(document.activeElement);
    		var listName = focused.prop('id') + "-aclist";
    		var fList = $('#'+listName);
    		if (fList.length) {
	    		if (fList.children('.acItem').length > 0) {
					e.preventDefault();
	    			var selected = fList.children('li.acItem-selected');
	    			if (selected.length > 0) {
	    				selected.removeClass('acItem-selected');
	    				selected = selected.first();
	    			}
	    			var toSelect;

	    			if (e.which == 13 || e.keyCode == 13 || e.which == 9 || e.keyCode == 9) {
	    				// select current item
	    				e.preventDefault();
	    				e.stopPropagation();
	    				if (selected.length > 0) {
	    					$(document).data('Autocomplete', true);
	    					selected.click();
	    				}
	    				return;

	    			} else if (e.which == 40 || e.keyCode == 40) {
	    				// Down
	    				if (selected.length > 0) {
	    					while (!toSelect) {
	    						if (!selected || selected.length == 0) {
	    							toSelect = fList.children('.acItem').first();
	    						} else if (selected.get(0) == (fList.children('.acItem').last().get(0))) {
	    							if(fList.children('.acFinal')) {
										fList.children('.acFinal').click();
										if (!selected.next().is(':visible')) {
			    							selected = selected.next();
			    						}else {
			    							toSelect = selected.next();
			    						}
	    							} else {
	    								toSelect = fList.children('.acItem').first();
	    							}
		    					} else {
		    						// Skip hidden items
		    						if (!selected.next().is(':visible')) {
		    							selected = selected.next();
		    						}else {
		    							toSelect = selected.next();
		    						}
		    					}
	    					}
	    				} else {
	    					if(fList.children('.acItem-next').length > 0){
	    						toSelect = fList.children('.acItem-next').first();
		    					fList.children('.acItem-next').first().removeClass('acItem-next');
	    					}else{
	    						toSelect = fList.children('.acItem').first();
	    					}
	    				}
	    			} else if (e.which == 38 || e.keyCode == 38) {
	    				// Up
	    				if (selected.length > 0) {
	    					while (!toSelect) {
	    						if (!selected || selected.length == 0) {
	    							toSelect = fList.children('.acItem').last();
	    						} else if (selected == (fList.children('.acItem').first())) {
		    						toSelect = fList.children('.acItem').last();
		    					} else {
		    						// Skip hidden items
		    						if (!selected.prev().is(':visible')) {
		    							selected = selected.prev();
		    						} else {
		    							toSelect = selected.prev();
		    						}
		    					}
	    					}
	    				} else {
	    					if(fList.children('.acItem-next').length > 0){
	    						toSelect = fList.children('.acItem-next').first();
		    					fList.children('.acItem-next').first().removeClass('acItem-next');
	    					}else{
	    						toSelect = fList.children('.acItem').first();
	    					}	    				}
	    			}
	    			if (toSelect.length > 0) {
	    				fList.scrollTop(toSelect[0].offsetTop - (fList.height()/2));
	    				toSelect.addClass('acItem-selected');
	    			}
	    		}
	    		if (e.which == 13 || e.keyCode == 13 || e.which == 9 || e.keyCode == 9) {
    				e.preventDefault();
    				e.stopPropagation();
	    		}
    		}
    	});
    };

    selfservice.showSiblings = function(index, field, skip) {
    	var parent = selfservice.getParent(index, field);
    	parent.siblings().each(function(){
    		$(this).removeClass("ss-hidden");
    	});
    	field.html(messageStrings[selectedLanguage].Page_multiInstances_showLess);
    	field.attr("onClick", "selfservice.hideSiblings(" + index + ", $(this), " + skip + ")");
    };

    selfservice.hideSiblings = function(index, field, skip) {
    	var parent = selfservice.getParent(index, field);
    	parent.siblings().each(function(i){
    		if(i > skip) {
    			$(this).addClass("ss-hidden");
    		}
    	});
    	field.html(messageStrings[selectedLanguage].Page_multiInstances_showMore);
    	field.attr("onClick", "selfservice.showSiblings(" + index + ", $(this), " + skip + ")");
    };

    selfservice.getParent = function(index, field) {
    	var parent = field;
    	for(var i = 0; i < index; i++) {
    		parent = parent.parent();
    	}
    	return parent;
    };

    selfservice.dateBlurCallback = function(event) {
    	var parsed = selfservice.parseDateShortcuts(event.target.value);
    	if (parsed instanceof Date) {
    		event.target.value = moment(parsed).format("MM/DD/YYYY");
    	}
		var showError = !(event.target.value === "");
    	
		var val = parsed == null ? event.target.value : parsed;
		var el = document.getElementById(event.target.id);
		if(!moment(val,["MM/DD/YYYY","M/D/YYYY","MM-DD-YYYY","M-D-YYYY","MMDDYYYY"],true).isValid()){
			if(showError){
				$( '<span id = "' + event.target.id + '-yearError" style="color:red">Format: MM/DD/YYYY</span>' ).insertBefore( el.closest("div"));
				document.getElementById(event.target.id).value ="";
			}
		}
    };

    selfservice.parseDateShortcuts = function(date) {
    	var dateIn = date.toLowerCase();

    	// Look for date offsets (+/-)
    	var reg = new RegExp(/[+-]\d+/);
    	var offset = 0;
    	if (reg.test(dateIn)) {
    		var offsetChunk = reg.exec(dateIn);
    		dateIn = dateIn.replace(offsetChunk, "");
    		offset = parseInt(offsetChunk);
    	}

        if (~dateIn.indexOf("sow")) {
            var d = moment().startOf('week');
            d.add(1, 'day'); // to get start of work week
            d.add(offset, 'week'); // add offset weeks
            return d.toDate();
        }
        if (~dateIn.indexOf("som")) {
        	var d = moment().startOf('month').add(offset, 'month');
        	return d.toDate();
        }
        if (~dateIn.indexOf("soy")) {
        	var d = moment().startOf('year').add(offset, 'year');
        	return d.toDate();
        }
        if (~dateIn.indexOf("eow")) {
        	var d = moment().endOf('week');
        	d.add(-1, "day"); // to get end of work week
        	d.add(offset, 'week'); // add offset weeks
        	return d.toDate();
        }
        if (~dateIn.indexOf("eom")) {
        	var d = moment().add(offset, 'month').endOf('month');
        	return d.toDate();
        }
        if (~dateIn.indexOf("eoy")) {
        	var d = moment().endOf('year').add(offset, 'year');
        	return d.toDate();
        }

        // Since we don't use time in SS, all these time-based shortcuts get substituted with the current date
    	if (~dateIn.indexOf("sod") || ~dateIn.indexOf("eod") || ~dateIn.indexOf("now") || ~dateIn.indexOf("noon") || (~dateIn.indexOf("t") && dateIn.length == 1)) {
        	var d = moment().add(offset, 'day');
        	return d.toDate();
        }
    };

    //following variable
    var currentDocumentNumber;

	selfservice.displayCantPrintMessage = function(pageCount){
		alert(messageStrings[selectedLanguage].Standard_print_cantPrintLargeImage);
	}
})(window.selfservice = window.selfservice || {});

// Extend jQuery.serializeArray() to always include a value for booleans so multi-instance presentations work
$.fn.extend({
    serializeArray: function() {
        var map = this.map(function(){
            return this.elements ? jQuery.makeArray( this.elements ) : this;
        })
        .filter(function(){
            return this.name && jQuery(this).prop('type') != 'fieldset' && !this.disabled &&
            (this.checked || !this.checked || rselectTextarea.test( this.nodeName ) || rinput.test( this.type ));
        })
        .map(function( i, elem ){
        var val = jQuery( this ).val();
        if ((jQuery(this).prop('type') == 'checkbox') && (jQuery(this).prop('checked') != undefined) && (!jQuery(this).prop('checked'))) {
            val = "";
        }
        // Unchecked radio buttons should not give us data
        if ((jQuery(this).prop('type') == 'radio') && ((jQuery(this).prop('checked') == undefined) || (!jQuery(this).prop('checked')))) {
        	return null;
        }
        return val == null ?
                null :
                    jQuery.isArray( val ) ?
                        jQuery.map( val, function( val, i ){
                            return { name: elem.name, value: val.replace( /\r?\n/g, "\r\n" ) };
                        }) :
                        { name: elem.name, value: val.replace( /\r?\n/g, "\r\n" ) };

        }).get();
        return map;
    }
});