/*
 * script.js - the small bits of interaction in the browser.
 *
 *  0. "Are you sure?" questions (forms with data-confirm)
 *  1. "Add another team" rows on the add-teams page
 *  2. The schedule slides (each batch is only loaded when somebody opens it;
 *     on phones you can swipe between batches)
 *  3. The pop-up when a manager clicks on a court
 *  4. The "Update time" wheel picker (hours and minutes you can drag)
 */


/* ======================================================================
 * Forms with data-confirm="question" ask the question before they are sent
 * (e.g. "Remove this team?"). Cancel = nothing happens.
 * ====================================================================== */
document.addEventListener("submit", function (event) {
    var question = event.target.dataset ? event.target.dataset.confirm : null;
    if (question && !window.confirm(question)) {
        event.preventDefault();
    }
});

/* Links with data-open-details="id" open the collapsed section with that id
 * (e.g. the "Edit / remove teams" button opens the Teams list). */
function openDetailsIn(id) {
    var section = document.getElementById(id);
    var details = section ? section.querySelector("details") : null;
    if (details) {
        details.open = true;
    }
}
document.addEventListener("click", function (event) {
    var link = event.target.closest("[data-open-details]");
    if (link) {
        openDetailsIn(link.dataset.openDetails);
    }
});
if (location.hash.length > 1) {
    openDetailsIn(location.hash.slice(1));
}


/* ======================================================================
 * 1. Add teams form
 * ====================================================================== */
function setUpTeamRows() {
    var rowsBox = document.getElementById("team-rows");
    var addButton = document.getElementById("add-row");

    // Copy the last row, empty it and put it at the bottom
    addButton.addEventListener("click", function () {
        var rows = rowsBox.querySelectorAll(".team-row");
        var lastRow = rows[rows.length - 1];
        var newRow = lastRow.cloneNode(true);
        newRow.querySelectorAll("input").forEach(function (input) {
            input.value = "";
        });
        // Keep the league of the row above: handy when typing a whole league
        newRow.querySelector("select").value = lastRow.querySelector("select").value;
        rowsBox.appendChild(newRow);
        newRow.querySelector("input").focus();
    });

    // The ✕ button removes a row (the last remaining row is only emptied)
    rowsBox.addEventListener("click", function (event) {
        if (!event.target.classList.contains("remove-row")) {
            return;
        }
        var row = event.target.closest(".team-row");
        if (rowsBox.querySelectorAll(".team-row").length > 1) {
            row.remove();
        } else {
            row.querySelectorAll("input").forEach(function (input) {
                input.value = "";
            });
        }
    });
}


/* ======================================================================
 * League rows in the tournament form
 * ====================================================================== */
function setUpLeagueRows() {
    var rowsBox = document.getElementById("league-rows");
    var addButton = document.getElementById("add-league");

    addButton.addEventListener("click", function () {
        // A new league has an empty league_id: the server will create it
        var row = document.createElement("div");
        row.className = "league-row";
        row.innerHTML =
            '<input type="hidden" name="league_id" value="">' +
            '<input type="text" name="league_name" maxlength="40" placeholder="League name" aria-label="League name">' +
            '<span class="small muted league-count"></span>' +
            '<button type="button" class="button button-small remove-league" title="Remove this league">✕</button>';
        rowsBox.appendChild(row);
        row.querySelector("input[type=text]").focus();
    });

    rowsBox.addEventListener("click", function (event) {
        if (!event.target.classList.contains("remove-league")) {
            return;
        }
        if (rowsBox.querySelectorAll(".league-row").length === 1) {
            alert("A tournament needs at least one league.");
            return;
        }
        event.target.closest(".league-row").remove();
    });
}


/* ======================================================================
 * League tabs on the dashboard (one panel per league)
 * ====================================================================== */
function setUpLeagueTabs() {
    var section = document.getElementById("leagues");
    if (!section) {
        return;
    }
    var tabs = section.querySelectorAll(".league-tab");
    var panels = section.querySelectorAll(".league-panel");
    // Remember the chosen league per tournament (only in this browser)
    var storageKey = "league-tab-" + section.dataset.tournament;

    function showLeague(leagueId) {
        var found = false;
        tabs.forEach(function (tab) {
            var active = tab.dataset.league === leagueId;
            tab.classList.toggle("is-active", active);
            tab.setAttribute("aria-selected", active ? "true" : "false");
            if (active) {
                found = true;
            }
        });
        if (!found) {
            return false;
        }
        panels.forEach(function (panel) {
            panel.hidden = panel.dataset.league !== leagueId;
        });
        return true;
    }

    tabs.forEach(function (tab) {
        tab.addEventListener("click", function () {
            showLeague(tab.dataset.league);
            try {
                localStorage.setItem(storageKey, tab.dataset.league);
            } catch (error) {
                // Private browsing: just do not remember it
            }
        });
    });

    try {
        var saved = localStorage.getItem(storageKey);
        if (saved) {
            showLeague(saved);
        }
    } catch (error) {
        // Nothing saved: the first league stays open
    }
}


/* ======================================================================
 * Pop-up windows (modals)
 * ====================================================================== */
function openModal(modal) {
    modal.hidden = false;
    document.body.classList.add("modal-open");
}

function closeModals() {
    document.querySelectorAll(".modal").forEach(function (modal) {
        modal.hidden = true;
    });
    document.body.classList.remove("modal-open");
}

// Remember where the mouse button went down, so that dragging a time wheel and
// letting go above the dark background does not close the pop-up by accident
var mouseDownTarget = null;
document.addEventListener("mousedown", function (event) {
    mouseDownTarget = event.target;
});

document.addEventListener("click", function (event) {
    // Buttons with data-close-modal, or a real click on the dark background
    var clickedBackground = event.target.classList.contains("modal") && mouseDownTarget === event.target;
    if (event.target.closest("[data-close-modal]") || clickedBackground) {
        closeModals();
    }
});

document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
        closeModals();
    }
});


/* ======================================================================
 * 2. Schedule slides
 * ====================================================================== */
function setUpSchedule() {
    var nav = document.getElementById("batch-nav");
    var slideArea = document.getElementById("slide-area");
    var pills = document.querySelectorAll(".batch-pill");
    var baseUrl = nav.dataset.baseUrl;            // e.g. "/tournament/1/batch/"
    var lastBatch = parseInt(nav.dataset.last, 10);
    var shownBatch = null;
    var loadedSlides = {};                         // batch number -> HTML (so we load each one once)

    function showBatch(batch) {
        if (batch < 1 || batch > lastBatch) {
            return;
        }
        shownBatch = batch;

        // Highlight the right button
        pills.forEach(function (pill) {
            var isActive = parseInt(pill.dataset.batch, 10) === batch;
            pill.classList.toggle("is-active", isActive);
            if (isActive) {
                pill.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
            }
        });

        if (loadedSlides[batch]) {
            slideArea.innerHTML = loadedSlides[batch];
            return;
        }

        // Not loaded yet: ask the server for this batch only
        slideArea.innerHTML = '<p class="muted slide-loading">Loading batch ' + batch + '…</p>';
        fetch(baseUrl + batch)
            .then(function (response) {
                if (!response.ok) {
                    throw new Error("Server answered " + response.status);
                }
                return response.text();
            })
            .then(function (html) {
                loadedSlides[batch] = html;
                if (shownBatch === batch) {
                    slideArea.innerHTML = html;
                }
            })
            .catch(function () {
                slideArea.innerHTML = '<p class="flash flash-error">Could not load batch ' + batch + '. Please try again.</p>';
            });
    }

    pills.forEach(function (pill) {
        pill.addEventListener("click", function () {
            showBatch(parseInt(pill.dataset.batch, 10));
        });
    });
    document.getElementById("batch-prev").addEventListener("click", function () {
        showBatch(shownBatch === null ? parseInt(nav.dataset.current, 10) : shownBatch - 1);
    });
    document.getElementById("batch-next").addEventListener("click", function () {
        showBatch(shownBatch === null ? parseInt(nav.dataset.current, 10) : shownBatch + 1);
    });

    // Arrow keys move between batches (when you are not typing in a field)
    document.addEventListener("keydown", function (event) {
        var typing = event.target.closest("input, select, textarea");
        var modalOpen = document.body.classList.contains("modal-open");
        if (typing || modalOpen || shownBatch === null) {
            return;
        }
        if (event.key === "ArrowLeft") {
            showBatch(shownBatch - 1);
        } else if (event.key === "ArrowRight") {
            showBatch(shownBatch + 1);
        }
    });

    // Phones: swipe left / right over the courts to go to the next / previous batch
    var touchStartX = null;
    var touchStartY = 0;
    slideArea.addEventListener("touchstart", function (event) {
        if (event.touches.length !== 1) {
            touchStartX = null;
            return;
        }
        touchStartX = event.touches[0].clientX;
        touchStartY = event.touches[0].clientY;
    }, { passive: true });
    slideArea.addEventListener("touchend", function (event) {
        if (touchStartX === null || shownBatch === null) {
            return;
        }
        var dx = event.changedTouches[0].clientX - touchStartX;
        var dy = event.changedTouches[0].clientY - touchStartY;
        touchStartX = null;
        // Only a clear sideways swipe, not scrolling the page up or down
        if (Math.abs(dx) > 60 && Math.abs(dx) > 2 * Math.abs(dy)) {
            showBatch(dx < 0 ? shownBatch + 1 : shownBatch - 1);
        }
    });

    // After a manager action the page comes back with ?batch=N: open that batch
    if (nav.dataset.open) {
        showBatch(parseInt(nav.dataset.open, 10));
        document.getElementById("schedule").scrollIntoView();
    } else {
        // Normal visit: show the current batch straight away
        showBatch(parseInt(nav.dataset.current, 10));
    }

}


/* ======================================================================
 * Manager buttons that work on every page (dashboard and team history):
 *   - anything with data-game-url (a court, or "Score / batch" button)
 *     opens the game pop-up
 *   - "Update start time" buttons open the time wheels
 * We listen on the whole document, so it also works for slides that are
 * loaded later.
 * ====================================================================== */
document.addEventListener("click", function (event) {
    // A click on a team name is a normal link to the team history page
    if (event.target.closest("a")) {
        return;
    }
    var timeButton = event.target.closest(".update-time-button");
    if (timeButton) {
        openTimePicker(timeButton);
        return;
    }
    var gameItem = event.target.closest("[data-game-url]");
    if (gameItem) {
        openGameOptions(gameItem.dataset.gameUrl);
    }
});

document.addEventListener("keydown", function (event) {
    var court = event.target.closest(".court-box.is-clickable");
    if (court && event.target === court && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        openGameOptions(court.dataset.gameUrl);
    }
});


/* ======================================================================
 * 3. Clicking on a court (managers only)
 * ====================================================================== */
function openGameOptions(url) {
    var modal = document.getElementById("game-modal");
    var content = document.getElementById("game-modal-content");
    content.innerHTML = "Loading…";
    openModal(modal);
    fetch(url)
        .then(function (response) {
            if (!response.ok) {
                throw new Error("Server answered " + response.status);
            }
            return response.text();
        })
        .then(function (html) {
            content.innerHTML = html;
            // With a mouse: start typing straight away. On a phone we do not, because
            // the keyboard would pop up and cover the "Change batch" options.
            var firstInput = content.querySelector("input[type=number]");
            var hasMouse = window.matchMedia && window.matchMedia("(pointer: fine)").matches;
            if (firstInput && hasMouse) {
                firstInput.focus();
            }
        })
        .catch(function () {
            content.innerHTML = '<p class="flash flash-error">Could not load this game. Are you still logged in?</p>';
        });
}


/* ======================================================================
 * 4. Time picker with two wheels (hours and minutes)
 * ====================================================================== */
var WHEEL_ITEM_HEIGHT = 40;   // must match .wheel-item height in style.css
var WHEEL_PADDING_ITEMS = 2;  // empty items above/below so 00 and 59 can reach the middle

function twoDigits(number) {
    return (number < 10 ? "0" : "") + number;
}

function buildWheel(wheel, numberOfValues) {
    wheel.innerHTML = "";
    var i;
    for (i = 0; i < WHEEL_PADDING_ITEMS; i++) {
        wheel.appendChild(makeWheelItem("", null));
    }
    for (i = 0; i < numberOfValues; i++) {
        wheel.appendChild(makeWheelItem(twoDigits(i), i));
    }
    for (i = 0; i < WHEEL_PADDING_ITEMS; i++) {
        wheel.appendChild(makeWheelItem("", null));
    }
    wheel.dataset.count = numberOfValues;
    wheel.addEventListener("scroll", function () {
        markSelectedItem(wheel);
        updateTimePreview();
    });
    makeWheelDraggable(wheel);
}

function makeWheelItem(text, value) {
    var item = document.createElement("div");
    item.className = value === null ? "wheel-spacer" : "wheel-item";
    item.textContent = text;
    if (value !== null) {
        item.dataset.value = value;
    }
    return item;
}

function getWheelValue(wheel) {
    var value = Math.round(wheel.scrollTop / WHEEL_ITEM_HEIGHT);
    var highest = parseInt(wheel.dataset.count, 10) - 1;
    return Math.max(0, Math.min(highest, value));
}

function setWheelValue(wheel, value, smooth) {
    wheel.scrollTo({ top: value * WHEEL_ITEM_HEIGHT, behavior: smooth ? "smooth" : "auto" });
    markSelectedItem(wheel);
}

function markSelectedItem(wheel) {
    var selected = getWheelValue(wheel);
    wheel.querySelectorAll(".wheel-item").forEach(function (item) {
        item.classList.toggle("selected", parseInt(item.dataset.value, 10) === selected);
    });
}

// Mouse dragging (touch screens and mouse wheels already scroll by themselves)
function makeWheelDraggable(wheel) {
    var dragging = false;
    var moved = false;
    var startY = 0;
    var startScroll = 0;

    wheel.addEventListener("mousedown", function (event) {
        dragging = true;
        moved = false;
        startY = event.clientY;
        startScroll = wheel.scrollTop;
        wheel.classList.add("dragging");     // switches off snapping while dragging
        event.preventDefault();
    });
    window.addEventListener("mousemove", function (event) {
        if (!dragging) {
            return;
        }
        var distance = event.clientY - startY;
        if (Math.abs(distance) > 3) {
            moved = true;
        }
        wheel.scrollTop = startScroll - distance;
    });
    window.addEventListener("mouseup", function () {
        if (!dragging) {
            return;
        }
        dragging = false;
        wheel.classList.remove("dragging");
        setWheelValue(wheel, getWheelValue(wheel), true);   // snap to the nearest number
    });
    // A simple click on a number selects it
    wheel.addEventListener("click", function (event) {
        var item = event.target.closest(".wheel-item");
        if (item && !moved) {
            setWheelValue(wheel, parseInt(item.dataset.value, 10), true);
        }
    });
}

function updateTimePreview() {
    var hours = getWheelValue(document.getElementById("hour-wheel"));
    var minutes = getWheelValue(document.getElementById("minute-wheel"));
    var text = twoDigits(hours) + ":" + twoDigits(minutes);
    document.getElementById("time-value").value = text;
    document.getElementById("time-preview").textContent = text;
}

function setUpTimePicker() {
    var hourWheel = document.getElementById("hour-wheel");
    if (!hourWheel) {
        return;   // not a manager
    }
    buildWheel(hourWheel, 24);
    buildWheel(document.getElementById("minute-wheel"), 60);
}

// Build the wheels as soon as the page is loaded (only managers have them)
setUpTimePicker();

function openTimePicker(button) {
    var modal = document.getElementById("time-modal");
    document.getElementById("time-batch-label").textContent = button.dataset.batch;
    document.getElementById("time-form").action = button.dataset.url;

    // Start the wheels at the estimated time (or now, if there is none)
    var hours;
    var minutes;
    var parts = button.dataset.time.split(":");
    if (parts.length === 2 && !isNaN(parseInt(parts[0], 10))) {
        hours = parseInt(parts[0], 10);
        minutes = parseInt(parts[1], 10);
    } else {
        var now = new Date();
        hours = now.getHours();
        minutes = now.getMinutes();
    }

    openModal(modal);   // the wheels must be visible before we can scroll them
    setWheelValue(document.getElementById("hour-wheel"), hours, false);
    setWheelValue(document.getElementById("minute-wheel"), minutes, false);
    updateTimePreview();
}
