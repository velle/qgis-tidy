(: apply_rules.xqy
   XQuery Update script equivalent to your YAML rules.
   Compatible with processors that implement XQuery Update (e.g., BaseX; Saxon PE/EE).

   Rules implemented:
     1) //layer-tree-layer[@name='hed_kabel']/@checked := "Qt::Checked"
     2) //layer-tree-layer[@name='roads'] set_attr checked=Qt::Unchecked, expanded=Qt::Unchecked
     3) //layer-tree-layer[@name in ('roads','trees','bushes')] set_attr checked=..., expanded=...
     4) //layer-tree-group[@name='fav_gadelys']/layer-tree-layer set_attr checked=..., expanded=...

   Note about rule 5 in your YAML:
     - It selects the <datasource> element and then tries to set "text" to a *mapping* with keys 'checked'/'expanded'.
       That's not a valid text value. If you intended to *replace the datasource string*, uncomment the example below
       and set the literal string you want.
:)

declare namespace output = "http://www.w3.org/2010/xslt-xquery-serialization";

(: Helper to set (insert-or-replace) an attribute on one or more element nodes :)
declare updating function local:set-attr(
  $nodes as element()*,
  $name  as xs:string,
  $value as xs:string
) {
  for $n in $nodes
  return (
    if ($n/@*[name() = $name]) then
      replace value of node $n/@*[name() = $name] with $value
    else
      insert node attribute { $name } { $value } into $n
  )
};

(: 1) hed_kabel -> checked = Qt::Checked :)
local:set-attr(//layer-tree-layer[@name='hed_kabel'], "checked", "Qt::Checked");

(: 2) roads -> checked/expanded = Qt::Unchecked :)
local:set-attr(//layer-tree-layer[@name='roads'], "checked",  "Qt::Unchecked"),
local:set-attr(//layer-tree-layer[@name='roads'], "expanded", "Qt::Unchecked");

(: 3) roads/trees/bushes -> checked/expanded = Qt::Unchecked :)
local:set-attr(//layer-tree-layer[@name=("roads","trees","bushes")], "checked",  "Qt::Unchecked"),
local:set-attr(//layer-tree-layer[@name=("roads","trees","bushes")], "expanded", "Qt::Unchecked");

(: 4) All layers that are direct children of group fav_gadelys -> checked/expanded = Qt::Unchecked :)
local:set-attr(//layer-tree-group[@name='fav_gadelys']/layer-tree-layer, "checked",  "Qt::Unchecked"),
local:set-attr(//layer-tree-group[@name='fav_gadelys']/layer-tree-layer, "expanded", "Qt::Unchecked");

(: 5) OPTIONAL: If you want to replace the datasource text for the layer named fav_kabel,
       uncomment and set the literal string you need. :)
(: replace value of node
     (//maplayer[@id = //layer-tree-layer[@name='fav_kabel']/@id]/datasource/text())[1]
   with
     "url=https://example/wfs?service=WFS&version=2.0.0&request=GetFeature typename=ns:layer srsname=EPSG:25832"
:)

(: End of updates :)
() (: Return an empty result; updates are applied to the context document depending on processor invocation. :)
