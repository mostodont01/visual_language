pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Asks for a name (new branch, rename branch).
//   Enter: accept    Escape / click outside: cancel
Popup {
	id: root

	property string title: ""
	property string text: ""
	property string initialName: ""
	property string acceptText: "OK"

	signal accepted(string name)

	parent: Overlay.overlay
	anchors.centerIn: parent
	width: 400
	modal: true
	dim: true
	padding: 20
	closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

	background: Rectangle {
		color: "#202329"
		radius: 8
		border.color: "#383d46"
	}

	function accept() {
		if (nameField.text.trim() === "")
			return
		var name = nameField.text.trim()
		close()
		accepted(name)
	}

	onAboutToShow: nameField.text = initialName
	onOpened: {
		nameField.forceActiveFocus()
		nameField.selectAll()
	}

	ColumnLayout {
		width: parent.width
		spacing: 12

		Text {
			Layout.fillWidth: true
			text: root.title
			color: "#e3e7ed"
			font.pixelSize: 14
			font.weight: Font.DemiBold
			wrapMode: Text.WordWrap
		}

		Text {
			Layout.fillWidth: true
			visible: root.text !== ""
			text: root.text
			color: "#929ba8"
			font.pixelSize: 12
			wrapMode: Text.WordWrap
		}

		VTextField {
			id: nameField
			Layout.fillWidth: true
			maximumLength: 50
			onAccepted: root.accept()
		}

		RowLayout {
			Layout.fillWidth: true
			Layout.topMargin: 6
			spacing: 8

			Item { Layout.fillWidth: true }

			VButton {
				text: "Cancel"
				onClicked: root.close()
			}
			VButton {
				text: root.acceptText
				kind: "primary"
				enabled: nameField.text.trim() !== ""
				onClicked: root.accept()
			}
		}
	}
}
