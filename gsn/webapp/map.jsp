<%-- index.jsp --%>
<%@ page import="gsn.Main,gsn.http.ac.*,org.apache.log4j.Logger" %>

<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
"http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">
    <head>
        <meta http-equiv="Content-Type" content="text/html;charset=utf-8" />
        <title>GSN</title>
        <link rel="stylesheet" href="style/gsn.css" type="text/css" media="screen,projection" />
        <script type="text/javascript" src="js/jquery-latest.pack.js"></script>
        <script type="text/javascript" src="js/jquery-dom.js"></script>
        <script type="text/javascript" src="js/jquery.history.js"></script>
        <script type="text/javascript" src="js/jquery-tooltip.js"></script>

        <!-- Include Map engine-->
        <script src="http://maps.google.com/maps?file=api&amp;v=2&amp;key=ABQIAAAA2MV0HBY9S6-aGXtjN0b1ZxTNHpjHnpWHHgdGqnMBUpwQOS9hiRQYia2Wq5RjKhXafOPvhLZP4RAQOA" type="text/javascript"></script>
        <!--<script src="http://api.maps.yahoo.com/ajaxymap?v=3.0&appid=YahooDemo" type="text/javascript"></script>-->
        <script src="http://dev.virtualearth.net/mapcontrol/v3/mapcontrol.js" type="text/javascript"></script>
        <script type="text/javascript" src="js/mapstraction.js"></script>

        <script type="text/javascript" src="js/constants.js"></script>
        <script type="text/javascript" src="js/functions.js"></script>
        <script type="text/javascript" src="js/gsn.js"></script>

        <script type="text/javascript">
            <!--//<![CDATA[
            var mapProvider = null;

            $(document).ready(function() {


                mapProvider = GSN.util.getURLParam("mapProvider");
                if(mapProvider.indexOf("#")!=-1){ //remove hash if any
                    mapProvider = mapProvider.substring(0,mapProvider.indexOf("#"));
                }

                if(mapProvider==""){
                    mapProvider = DEFAULT_MAP_PROVIDER;
                }

                if(mapProvider=="google"){
                    $("#GM").attr("checked","checked");
                }
                if(mapProvider=="yahoo"){
                    $("#YM").attr("checked","checked");
                }
                if(mapProvider=="microsoft"){
                    $("#VE").attr("checked","checked");
                    $("#toggleallmarkers").remove(); // because marker.hide() not possible with VE
                }


                map = new Mapstraction('vsmap',mapProvider);



                //bind every buttons to javascript functionality (only once)
                $("#refreshall_timeout").bind("change",GSN.updateallchange);
                $("#refreshall").bind("click",GSN.updateall);
                $("#toggleallmarkers").bind("click",GSN.map.toggleAllMarkers);
                $("#navigation ul a.local").bind("click",function() { return GSN.nav($(this).text()); });


                GSN.load();
            });
            //]]>-->
        </script>





    </head>
    <body onunload="">

        <div id="container">
            <div id="header">
                <h1><a href="." id="gsn-name">GSN</a></h1>
            </div>
            <div id="navigation">
                <ul id="menu">
                    <li><a href="index.jsp#home">home</a></li>
                    <li><a href="data.jsp#data">data</a></li>
                    <li class="selected"><a href="map.jsp#map">map</a></li>
                    <li><a href="fullmap.jsp#fullmap">fullmap</a></li>
                    <% if (Main.getContainerConfig().isAcEnabled()==true) { %>
                    <li><a href="/gsn/MyAccessRightsManagementServlet">access rights management</a></li>
                    <% } else { %>
                    <% } %>
                </ul>
		    <% if (Main.getContainerConfig().isAcEnabled()==true) { %>
            <ul id="logintext"><%= displayLogin(request) %></ul>
            <% } else { %>
            <% } %>
            </div>
            <div id="main">
                <noscript><p class="error">Your browser doesn't appear to support JavaScript. This is most likely because you're using a text-based or otherwise non-graphical browser. Sadly, GSN require javascript in order to work properly. If you want to access directly the data, you can use the api at <a href="http://localhost:22001/gsn">http://localhost:22001/gsn</a>.</p></noscript>

                <div id="control">
                    <iframe name="webupload" style="border:0;height:0;width:0;"></iframe>
                    <div id="msg">Welcome to Global Sensor Networks. The first ten sensors are displayed by default, but you can easily close them with the <em>close all</em> button. By clicking on a virtual sensors on the left sidebar, it will bring it to the top of the list.</div>

                    <p>Auto-refresh every :
                        <select id="refreshall_timeout" >
                            <option value="3600000">1hour</option>
                            <option value="600000">10min</option>
                            <option value="60000" selected="selected">1min</option>
                            <option value="30000">30sec</option>
                            <option value="5000">5sec</option>
                            <option value="1000">1sec</option>
                            <option value="0">disable</option>
                        </select>
                        <input id="refreshall" type="button" value="refresh" />
                        <span class="refreshing"><img src="style/ajax-loader.gif" alt="loading" title="" /></span>
                    </p>
                </div>

                <div id="homediv">
                    <div id="vs">
                        <div class="loading">Virtual sensors are currently loading...</div>
                    </div>
                </div>


                <!-- map part -->
                <div id="mapdiv">

                    <!-- <h2>Global Sensor Network Map</h2> -->
                    <p><a style="text-decoration:underline" href="javascript:GSN.map.showAllMarkers();">Auto-zoom and focus the map</a></p>
                    <div id='selectMapProvider'>
                        <input type="radio" id="VE" class="mapProvider" name="mapProvider" onclick="location.href='map.html?mapProvider=microsoft';" value="VE">Virtual Earth
                        <input type="radio" id="GM" class="mapProvider" name="mapProvider" onclick="location.href='map.html?mapProvider=google';" value="GM">Google Maps
                        <!--<input type="radio" id="YM" class="mapProvider" name="mapProvider" onclick="location.href='map.html?mapProvider=yahoo';" value="YM">Yahoo Maps -->
                    </div>
                    <div id="vsmap" style="width: 100%; height: 500px; position:relative;"></div>
                    <div id="vs4map"></div>
                </div>

            </div>
            <div id="sidebar">
                <h3>Description</h3>
                <p id="gsn-desc">none</p>
                <h3>Author</h3>
                <p id="gsn-author">none</p>
                <h3>Virtual sensors</h3>
                <ul id="vsmenu">
                    <li><a href="#">not loaded</a></li>
                </ul>
                <p><input class="hidden" id="toggleallmarkers" type="button" value="Show/hide all markers" /></p>
            </div>
            <div id="footer">
                <p>You should first <a href="/gsn/loginhandlerservlet"> login </a> to GSN </p>
                 <p>GSN <a href="/gsn/logouthandlerservlet"> logout </a></p>
                <p>Powered by <a href="http://globalsn.sourceforge.net/">GSN</a>,  Distributed Information Systems Lab, EPFL 2006</p>
                <p>
                    <a href="http://validator.w3.org/check?uri=referer"><img src="./img/html_valid.bmp"/></a>
                    <a href="http://jigsaw.w3.org/css-validator/check?uri=referer"><img src="./img/css_valid.bmp"/></a>
                </p>
            </div>
        </div>
    </body>
</html>

<%!


private String displayLogin(HttpServletRequest req) {

  String name=null;
  HttpSession session = req.getSession();
  User user = (User) session.getAttribute("user");
  if (user != null)
  {
    name="<li><a href=/gsn/MyLogoutHandlerServlet> logout </a></li>"+"<li><div id=logintextprime >logged in as: "+user.getUserName()+"&nbsp"+"</div></li>";

  }
  else
  {
    name="";
  }
  return name;
}
%>
