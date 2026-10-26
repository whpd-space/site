// Mobile menu toggle
document.addEventListener('DOMContentLoaded', function() {
	const menuToggle = document.getElementById('menu-toggle');
	const navbar = document.getElementById('navbar');
	const easternTimeZone = 'America/New_York';
	const fleetWelcome = document.getElementById('memefleet-welcome');
	const fleetVideo = document.getElementById('memefleet-video');

	if (fleetWelcome && fleetVideo && typeof fleetWelcome.showModal === 'function') {
		const playbackStatus = document.getElementById('memefleet-playback-status');
		function enterFleetPage() {
			fleetVideo.muted = false;
			fleetVideo.volume = 1;
			// Start playback directly in the click handler to preserve user activation.
			const playback = fleetVideo.play();
			fleetWelcome.close();
			if (playback) {
				playback.catch(function() {
					playbackStatus.textContent = 'Press play on the video to watch with sound.';
					playbackStatus.hidden = false;
				});
			}
		}
		document.getElementById('memefleet-enter').addEventListener('click', enterFleetPage);
		fleetWelcome.addEventListener('cancel', function(event) {
			event.preventDefault();
			enterFleetPage();
		});
		fleetWelcome.addEventListener('close', function() {
			fleetVideo.focus({ preventScroll: true });
		});
		fleetVideo.addEventListener('playing', function() {
			playbackStatus.hidden = true;
		});
		fleetWelcome.showModal();
	}

	function getDatePartsInTimeZone(date, timeZone) {
		const formatter = new Intl.DateTimeFormat('en-US', {
			timeZone,
			weekday: 'short',
			year: 'numeric',
			month: '2-digit',
			day: '2-digit',
			hour: '2-digit',
			minute: '2-digit',
			hour12: false,
		});

		const parts = formatter.formatToParts(date);
		const map = {};
		parts.forEach(part => {
			if (part.type !== 'literal') {
				map[part.type] = part.value;
			}
		});

		const weekdayMap = {
			Sun: 0,
			Mon: 1,
			Tue: 2,
			Wed: 3,
			Thu: 4,
			Fri: 5,
			Sat: 6,
		};

		return {
			weekday: weekdayMap[map.weekday],
			year: Number(map.year),
			month: Number(map.month),
			day: Number(map.day),
			hour: Number(map.hour),
			minute: Number(map.minute),
		};
	}

	function getTimeZoneOffsetMinutes(date, timeZone) {
		const formatter = new Intl.DateTimeFormat('en-US', {
			timeZone,
			timeZoneName: 'shortOffset',
			hour: '2-digit',
			minute: '2-digit',
			hour12: false,
		});

		const parts = formatter.formatToParts(date);
		const offsetPart = parts.find(part => part.type === 'timeZoneName');
		if (!offsetPart) {
			return 0;
		}

		const match = offsetPart.value.match(/GMT([+-])(\d{1,2})(?::?(\d{2}))?/);
		if (!match) {
			return 0;
		}

		const sign = match[1] === '-' ? -1 : 1;
		const hours = Number(match[2]);
		const minutes = Number(match[3] || 0);
		return sign * (hours * 60 + minutes);
	}

	function getNextSundayFleetInEastern() {
		const now = new Date();
		const easternNow = getDatePartsInTimeZone(now, easternTimeZone);
		let daysUntilSunday = (7 - easternNow.weekday) % 7;

		if (daysUntilSunday === 0) {
			const hasPassedToday = easternNow.hour > 13 || (easternNow.hour === 13 && easternNow.minute > 0);
			if (hasPassedToday) {
				daysUntilSunday = 7;
			}
		}

		const targetNoonUtc = new Date(Date.UTC(easternNow.year, easternNow.month - 1, easternNow.day + daysUntilSunday, 12, 0, 0));
		const offsetMinutes = getTimeZoneOffsetMinutes(targetNoonUtc, easternTimeZone);
		const utcMillis = Date.UTC(
			easternNow.year,
			easternNow.month - 1,
			easternNow.day + daysUntilSunday,
			13,
			0,
			0
		) - (offsetMinutes * 60 * 1000);

		return new Date(utcMillis);
	}

	function renderLocalFleetTime() {
		const localTimeElement = document.getElementById('fleet-time-local');
		if (!localTimeElement) {
			return;
		}

		const fleetDate = getNextSundayFleetInEastern();
		const localDisplay = new Intl.DateTimeFormat(undefined, {
			weekday: 'long',
			hour: 'numeric',
			minute: '2-digit',
			timeZoneName: 'short',
		}).format(fleetDate);

		const setupDate = new Date(fleetDate.getTime() - 30 * 60 * 1000);
		const setupDisplay = new Intl.DateTimeFormat(undefined, {
			hour: 'numeric',
			minute: '2-digit',
			timeZoneName: 'short',
		}).format(setupDate);

		localTimeElement.textContent = `Your time: ${localDisplay} (New Pilot setup starts at ${setupDisplay})`;
	}
	
	if (menuToggle && navbar) {
		menuToggle.addEventListener('click', function() {
			this.classList.toggle('active');
			navbar.classList.toggle('active');
			
			const isExpanded = this.classList.contains('active');
			this.setAttribute('aria-expanded', isExpanded);
		});
		
		// Close menu when clicking on a link
		const navLinks = navbar.querySelectorAll('a');
		navLinks.forEach(link => {
			link.addEventListener('click', function() {
				menuToggle.classList.remove('active');
				navbar.classList.remove('active');
				menuToggle.setAttribute('aria-expanded', 'false');
			});
		});
	}

	const yc_year = new Date().getFullYear() - 1898;
	const footer = `<p>&copy; YC ${yc_year} WHPD | ALL RIGHTS RESERVED</p>`;
	document.getElementById('footer').innerHTML = footer;
	renderLocalFleetTime();
});
