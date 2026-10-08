import unittest
from unittest.mock import Mock, patch
from src.utils.title_controls import title_text_targets, title_text_keys


def tool(name, reg, key, value='SAMPLE', connected=None, expression=None):
    t, inp = Mock(), Mock()
    t.GetAttrs.return_value = {'TOOLS_Name':name, 'TOOLS_RegID':reg}
    inp.GetAttrs.return_value = {'INPS_ID':key}
    inp.GetExpression.return_value = expression
    inp.GetConnectedOutput.return_value = connected
    t.GetInputList.return_value = {1:inp}
    t.GetInput.return_value = value
    return t


class TitleControlsTests(unittest.TestCase):
    def test_follower_base_text_is_targeted_without_disconnecting_animation(self):
        follower = tool('Follower1','StyledTextFollower','Text')
        output = Mock()
        output.GetTool.return_value = follower
        owner = tool('Text1','TextPlus','StyledText',connected=output)
        comp = Mock()
        comp.GetToolList.return_value = {1:owner,2:follower}
        targets, skipped = title_text_targets(comp)
        self.assertFalse(skipped)
        self.assertEqual([(t['tool_name'],t['input']) for t in targets],[('Follower1','Text')])
        owner.SetInput.assert_not_called()

    def test_shape_and_3d_text_are_supported_but_expressions_are_retained(self):
        comp = Mock()
        comp.GetToolList.return_value = {1:tool('Shape','sText','StyledText'),
            2:tool('3D','Text3D','StyledText'),3:tool('Expression','TextPlus','StyledText',expression='other.Text')}
        targets, skipped = title_text_targets(comp)
        self.assertEqual([t['tool_name'] for t in targets],['Shape','3D'])
        self.assertEqual(len(skipped),1)

    def test_unknown_modifier_is_not_flattened(self):
        output = Mock()
        output.GetTool.return_value = tool('Unknown','UnknownModifier','Text')
        comp = Mock()
        comp.GetToolList.return_value = {1:tool('Text','TextPlus','StyledText',connected=output)}
        targets, skipped = title_text_targets(comp)
        self.assertFalse(targets)
        self.assertIn('unsupported',skipped[0]['reason'])

    def test_published_text_value_is_targeted(self):
        published = tool('Publish1','PublishText','Value')
        output = Mock()
        output.GetTool.return_value = published
        comp = Mock()
        comp.GetToolList.return_value = {1:tool('3D','Text3D','StyledText',connected=output),2:published}
        targets, skipped = title_text_targets(comp)
        self.assertFalse(skipped)
        self.assertEqual([(t['tool_name'],t['input']) for t in targets],[('Publish1','Value')])

    def test_multitext_edits_rendered_text_not_passive_list_labels(self):
        multi = tool('Template','MultiText','TextValue2')
        inputs = {}
        for key in ['TextValue2','TextValue1','TextName1','TextValue1Clone1']:
            inp=Mock()
            inp.GetAttrs.return_value={'INPS_ID':key}
            inp.GetExpression.return_value=None
            inp.GetConnectedOutput.return_value=None
            inputs[key]=inp
        multi.GetInputList.return_value=inputs
        for index in (1,2):
            key=f'Text{index}.StyledText'
            inp=Mock()
            inp.GetAttrs.return_value={'INPS_ID':key}
            inp.GetExpression.return_value=None
            inp.GetConnectedOutput.return_value=None
            setattr(multi,key,inp)
        comp=Mock()
        comp.GetToolList.return_value={1:multi}
        targets, skipped=title_text_targets(comp)
        self.assertFalse(skipped)
        self.assertEqual([t['input'] for t in targets],['Text1.StyledText','Text2.StyledText'])
        multi.GetInput.side_effect = lambda k: {'TextOrder':{0:2,1:1},'TextEnabled1':1,'TextEnabled2':1}.get(k,'SAMPLE')
        self.assertEqual(title_text_keys(multi),['Text2.StyledText','Text1.StyledText'])
        self.assertEqual([t['input'] for t in title_text_targets(comp)[0]],['Text2.StyledText','Text1.StyledText'])

    def test_public_title_text_fallback_edits_follower_and_keeps_owner_connected(self):
        from src import server
        follower = tool('Follower1','StyledTextFollower','Text')
        follower.SetInput.side_effect = lambda key,value: setattr(follower.GetInput,'return_value',value)
        output = Mock()
        output.GetTool.return_value = follower
        owner = tool('Text1','TextPlus','StyledText',connected=output)
        comp, item = Mock(), Mock()
        comp.GetToolList.return_value = {1:owner,2:follower}
        item.GetFusionCompCount.return_value = 1
        item.GetFusionCompByIndex.return_value = comp
        item.SetProperty.return_value = False
        with patch.object(server,'_timeline_resolve_item_optional',return_value=(item,None)), \
             patch.object(server,'_timeline_item_get_property_map',return_value=({},None)):
            result = server._timeline_set_title_text(Mock(),{'text':'CHANGED'})
        self.assertTrue(result['success'])
        self.assertEqual(result['tool_name'],'Follower1')
        follower.SetInput.assert_called_once_with('Text','CHANGED')
        owner.SetInput.assert_not_called()
        owner.ConnectInput.assert_not_called()


if __name__ == '__main__':
    unittest.main()
