var NavBar = ` 
   <div id="bluespace">
      <img src="images/whpd-banner.png" alt="">
   </div>
  <div id="header">
   <div="navbar">
      <ul>
        <li><a href="/">Home</a></li>
        <li><a href="Mission.html">Mission</a></li>
        <li><a href="LegalLibrary.html">Legal Library</a></li>
        <li>
          <a href="#">Resources</a>
          <ul class="dropdown">
            <li><a href="MarkeeDragonRedirect.html">Markee Dragon</a></li>
            <li><a href="HighsecBuybackRedirect.html">Highsec Buyback</a></li>
            <li><a href="LowsecBuybackRedirect.html">Lowsec Buyback</a></li>
            <li><a href="FreeSkillPointsRedirect.html">Free Skill Points</a></li>
          </ul>
        </li>
        <li><a href="AboutUs.html">About Us</a></li>
        <li><a href="ContactUs.html">Contact Us</a></li>
      </ul>
    </div>
  </div>
  <div id="whitespace">
  </div>
`;

var Footer = ` 
  <div id="whitespace">
  </div>
  <div id="footer">
      <p>&copy; YC 127 WHPD | ALL RIGHTS RESERVED</p>
  </div>
`;

// inserting NavBar into header container
document.getElementById('header-container').innerHTML = NavBar;
        
// inserting Footer into footer container
document.getElementById('footer-container').innerHTML = Footer;
