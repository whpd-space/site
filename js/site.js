// Mobile menu toggle
document.addEventListener('DOMContentLoaded', function() {
	const menuToggle = document.getElementById('menu-toggle');
	const navbar = document.getElementById('navbar');
	
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
});
