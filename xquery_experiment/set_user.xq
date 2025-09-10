(: Requires an XQuery processor with Update Facility + fn:replace (XQuery 2.0+) :)

declare updating function local:set-elcon-user($new as xs:string) {
  for $ds in //maplayer[provider='wfs']/datasource
  let $s := string($ds)
  where matches($s,
    "url='https://elcon\.admin\.gc2\.io/wfs/[^@']+@elcon/[^/]+/25832'")
  return
    replace value of node $ds/text()
    with replace(
      $s,
      "url='https://elcon\.admin\.gc2\.io/wfs/[^@']+@elcon/([^/]+)/25832'",
      concat("url='https://elcon.admin.gc2.io/wfs/", $new, "@elcon/", "$1", "/25832'")
    )
};

(: usage :)
local:set-elcon-user("chbi")
