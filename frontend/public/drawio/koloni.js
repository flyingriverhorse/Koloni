/*
 * KOLONİ's side of the draw.io viewer (K-drawio), loaded before viewer-static.min.js. The same file
 * draws in the Workspace (viewer.html, in a sandboxed frame) and on the server (`app.diagram`, in the
 * headless browser of slice 51, on about:blank).
 *
 * Every address the viewer would load from - styles, stencils, shapes, its proxy, math, its own images,
 * diagrams.net itself - is "data:,": a URL that names no place, so nothing is asked of any server. (Not
 * "": the viewer takes an empty value for none given and puts diagrams.net's back.)
 */
;(function () {
  var NOWHERE = 'data:,'
  ;['PROXY_URL', 'STYLE_PATH', 'SHAPES_PATH', 'STENCIL_PATH', 'DRAW_MATH_URL', 'GRAPH_IMAGE_PATH', 'mxImageBasePath', 'mxBasePath',
    'DRAWIO_BASE_URL', 'DRAWIO_LIGHTBOX_URL', 'DRAWIO_SERVER_URL'].forEach(function (name) {
    window[name] = NOWHERE
  })
  window.mxLoadResources = false
  window.mxLoadStylesheets = false
  window.isLocalStorage = false
})()

var koloniViewer = null

/*
 * The diagram's XML with each page's model plain (not compressed), and every shape that has no geometry
 * given a place: in rows by its rank along the edges, sources on top - for the eye only, the file is not
 * changed. shortcut: viewer-static ships no hierarchical layout (its mxHierarchicalLayout became ELK,
 * which it does not bundle), so this is a plain longest-path ranking; shapes inside a group are placed as
 * if they were not. Bring a real layout in if diagrams written without geometry are seen to need one.
 */
function koloniLaidOut(xml) {
  var doc = mxUtils.parseXml(xml)
  var root = doc.documentElement
  if (!root || root.nodeName === 'parsererror' || root.getElementsByTagName('parsererror').length) throw new Error('This is not a draw.io file: its XML could not be read.')
  var models = []
  if (root.nodeName === 'mxGraphModel') models.push(root)
  var pages = root.getElementsByTagName('diagram')
  for (var p = 0; p < pages.length; p++) {
    var page = pages[p]
    var model = page.getElementsByTagName('mxGraphModel')[0]
    if (!model && page.textContent.trim()) {
      model = doc.importNode(mxUtils.parseXml(Graph.decompress(page.textContent.trim())).documentElement, true)
      page.textContent = ''
      page.appendChild(model)
    }
    if (model) models.push(model)
  }
  models.forEach(koloniPlace)
  return mxUtils.getXml(doc)
}

function koloniPlace(model) {
  var cells = model.getElementsByTagName('mxCell')
  var bare = []
  var edges = []
  for (var i = 0; i < cells.length; i++) {
    var cell = cells[i]
    // (A cell inside <object> or <UserObject> has its id on that.)
    var id = cell.getAttribute('id') || cell.parentNode.getAttribute('id')
    var placed = false
    for (var child = cell.firstChild; child; child = child.nextSibling) placed = placed || (child.nodeName === 'mxGeometry' && child.getAttribute('as') === 'geometry')
    if (cell.getAttribute('vertex') === '1' && !placed) bare.push({ id: id, cell: cell })
    if (cell.getAttribute('edge') === '1') {
      edges.push([cell.getAttribute('source'), cell.getAttribute('target')])
      // (An edge with no geometry is not drawn at all: it runs from its source to its target.)
      if (!placed) cell.appendChild(koloniGeometry(model, { relative: '1' }))
    }
  }
  if (!bare.length) return
  var rank = {}
  bare.forEach(function (one) {
    rank[one.id] = 0
  })
  // (At most one pass a shape: a cycle stops there.)
  for (var pass = 0; pass < bare.length; pass++) {
    var moved = false
    edges.forEach(function (edge) {
      if (edge[0] in rank && edge[1] in rank && rank[edge[1]] < rank[edge[0]] + 1 && rank[edge[0]] + 1 < bare.length) {
        rank[edge[1]] = rank[edge[0]] + 1
        moved = true
      }
    })
    if (!moved) break
  }
  var inRow = {}
  bare.forEach(function (one) {
    var row = rank[one.id]
    var column = (inRow[row] = (inRow[row] || 0) + 1) - 1
    one.cell.appendChild(koloniGeometry(model, { x: String(column * 180), y: String(row * 120), width: '140', height: '60' }))
  })
}

function koloniGeometry(model, at) {
  var geometry = model.ownerDocument.createElement('mxGeometry')
  Object.keys(at).forEach(function (name) {
    geometry.setAttribute(name, at[name])
  })
  geometry.setAttribute('as', 'geometry')
  return geometry
}

/** Draws the diagram in #diagram (made if missing): zoom, pages and layers in its toolbar; no link out of it. */
function koloniShow(xml) {
  // (No stencil script is fetched and run: none could be anyway, nothing is loaded.)
  mxStencilRegistry.allowEval = false
  mxStencilRegistry.dynamicLoading = false
  var box = document.getElementById('diagram')
  if (!box) {
    box = document.createElement('div')
    box.id = 'diagram'
    document.body.appendChild(box)
  }
  box.textContent = ''
  koloniViewer = new GraphViewer(box, mxUtils.parseXml(koloniLaidOut(xml)).documentElement, {
    toolbar: 'pages zoom layers',
    'toolbar-nohide': true,
    lightbox: false,
    nav: true,
    resize: false,
    'auto-fit': true,
    center: true,
    'dark-mode': false,
    border: 20,
  })
}

/** The page shown as a picture: the SVG's text, or a PNG (at twice its size, on white) as a data: URL. */
function koloniPicture(format) {
  var graph = koloniViewer.graph
  var svg = '<?xml version="1.0" encoding="UTF-8"?>\n' + mxUtils.getXml(graph.getSvg(format === 'png' ? '#ffffff' : null, 1, 10))
  if (format !== 'png') return Promise.resolve(svg)
  return new Promise(function (done, fail) {
    var image = new Image()
    image.onload = function () {
      var canvas = document.createElement('canvas')
      canvas.width = image.width * 2
      canvas.height = image.height * 2
      canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height)
      done(canvas.toDataURL('image/png'))
    }
    image.onerror = function () {
      fail(new Error('The picture could not be drawn.'))
    }
    image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg)
  })
}

/** On the server: the diagram drawn, as `koloniPicture` gives it. */
window.koloniDraw = function (xml, format) {
  koloniShow(xml)
  return koloniPicture(format)
}

// In the Workspace: the app posts the file's text ({xml}), then asks for a picture of it ({save: 'png' | 'svg'}).
// Only the frame's own parent is heard, and answered - at the origin this page is served from (`location.origin`, its
// address's: the page itself is of no origin).
window.addEventListener('message', function (event) {
  var said = event.data
  if (event.source !== window.parent || event.origin !== location.origin || !said || typeof said !== 'object') return
  var answer = function (message) {
    window.parent.postMessage(message, location.origin)
  }
  if (typeof said.xml === 'string') {
    try {
      koloniShow(said.xml)
      answer({ shown: true })
    } catch (error) {
      answer({ failed: String((error && error.message) || error) })
    }
  } else if ((said.save === 'png' || said.save === 'svg') && koloniViewer) {
    koloniPicture(said.save).then(
      function (data) {
        answer({ saved: said.save, data: data })
      },
      function (error) {
        answer({ failed: String((error && error.message) || error) })
      },
    )
  }
})
